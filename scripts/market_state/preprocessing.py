"""Model-independent, strictly train-fitted column and nominal-state handling."""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator,TransformerMixin
from sklearn.utils.validation import check_is_fitted
import copy
import json
import joblib
from pathlib import Path
from .common import digest
from .model_contract import CONTRACT_VERSION

def nominal(name):
    return name=='current_state_id' or name.startswith('current_state_id_lag')

class FoldPreprocessor(TransformerMixin,BaseEstimator):
    def fit(self,X,y=None):
        if not isinstance(X,pd.DataFrame) or not X.columns.is_unique:raise ValueError('Named unique feature columns required')
        self.feature_names_in_=np.asarray(X.columns,dtype=object)
        self.dtypes_=X.dtypes.astype(str).to_dict()
        self.categorical_=[c for c in X if nominal(c)];self.numeric_=[c for c in X if c not in self.categorical_]
        n=X[self.numeric_].astype(float)
        if np.isinf(n.to_numpy()).any():raise ValueError('Infinite input feature')
        self.all_empty_=[c for c in n if n[c].isna().all()]
        self.constant_=[c for c in n if c not in self.all_empty_ and n[c].nunique(dropna=True)<=1]
        self.retained_=[c for c in n if c not in self.all_empty_+self.constant_]
        self.median_=n[self.retained_].median()
        self.scale_=n[self.retained_].quantile(.75)-n[self.retained_].quantile(.25)
        self.scale_=self.scale_.where(self.scale_.gt(0),1.)
        self.categories_={c:sorted(X[c].dropna().unique().tolist()) for c in self.categorical_}
        names=list(self.retained_)+['missing__'+c for c in self.numeric_]
        for c,values in self.categories_.items():names += [c+'=='+str(v) for v in values]+[c+'==MISSING',c+'==UNSEEN']
        if len(names)!=len(set(names)):raise ValueError('Encoded feature names collide')
        self.output_names_=np.asarray(names,dtype=object)
        self._schema();return self

    def transform(self,X):
        check_is_fitted(self,'output_names_')
        if list(X.columns)!=list(self.feature_names_in_):raise ValueError('Validation/test input column order differs from training')
        if X.dtypes.astype(str).to_dict()!=self.dtypes_:raise ValueError('Input dtype differs from fitted schema')
        n=X[self.numeric_].astype(float)
        if np.isinf(n.to_numpy()).any():raise ValueError('Infinite input feature')
        values=(n[self.retained_].fillna(self.median_)-self.median_)/self.scale_
        parts=[values.to_numpy(float),n.isna().to_numpy(float)]
        for c,categories in self.categories_.items():
            parts += [np.column_stack([X[c].eq(v).fillna(False).to_numpy(float) for v in categories]+[
                X[c].isna().to_numpy(float),(X[c].notna()&~X[c].isin(categories)).to_numpy(float)])]
        result=np.concatenate(parts,axis=1)
        if not np.isfinite(result).all():raise ValueError('Non-finite preprocessed features')
        return result

    def get_feature_names_out(self,input_features=None):
        check_is_fitted(self,'output_names_');return self.output_names_.copy()

    def subset(self,columns):
        """Exact restriction of univariate training statistics, without refitting."""
        if not set(columns)<=set(self.feature_names_in_):raise ValueError('Unknown subset column')
        check_is_fitted(self,'output_names_')
        p=copy.copy(self);p.feature_names_in_=np.asarray(columns,dtype=object)
        p.dtypes_={c:self.dtypes_[c] for c in columns}
        for name in ['categorical_','numeric_','all_empty_','constant_','retained_']:
            setattr(p,name,[c for c in getattr(self,name) if c in columns])
        p.median_=self.median_.reindex(p.retained_);p.scale_=self.scale_.reindex(p.retained_)
        p.categories_={c:self.categories_[c] for c in p.categorical_}
        names=p.retained_+['missing__'+c for c in p.numeric_]
        for c,values in p.categories_.items():names += [c+'=='+str(v) for v in values]+[c+'==MISSING',c+'==UNSEEN']
        p.output_names_=np.asarray(names,dtype=object)
        # Restricting columns is an unbound statistics view; fit_inputs binds a formal instance.
        if hasattr(p,'fit_context_'):del p.fit_context_
        p._schema();return p

    def _schema(self):
        self.schema_=dict(contract_version=CONTRACT_VERSION,raw_columns=self.feature_names_in_.tolist(),raw_dtypes=self.dtypes_,
            output_columns=self.output_names_.tolist(),output_dtype='float64',
            categorical=self.categories_,all_empty=self.all_empty_,constant=self.constant_,
            retained=self.retained_,median=self.median_.to_dict(),scale=self.scale_.to_dict(),
            missing='training median + fixed numeric missing indicators; nominal MISSING/UNSEEN',
            scaling='univariate train IQR; nonpositive IQR uses 1; numeric empty/constant values dropped')
        self.refresh_schema_version()

    def refresh_schema_version(self):
        self.schema_.pop('schema_version',None)
        self.schema_['schema_version']=digest(self.schema_)

    def save(self,path):
        check_is_fitted(self,'output_names_');path=Path(path);path.mkdir(parents=True,exist_ok=True)
        joblib.dump(self,path/'preprocessor.joblib')
        (path/'input_schema.json').write_text(json.dumps(self.schema_,ensure_ascii=False,indent=2),encoding='utf8')

    @classmethod
    def load(cls,path):
        path=Path(path);p=joblib.load(path/'preprocessor.joblib')  # trusted local artifacts only
        schema=json.loads((path/'input_schema.json').read_text(encoding='utf8'))
        if not isinstance(p,cls) or p.schema_!=schema or schema['contract_version']!=CONTRACT_VERSION:raise ValueError('Preprocessor/schema mismatch')
        if digest({k:v for k,v in schema.items() if k!='schema_version'})!=schema['schema_version']:raise ValueError('Preprocessor schema identity mismatch')
        return p
