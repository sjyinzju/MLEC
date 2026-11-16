"""Model-independent, strictly train-fitted column and nominal-state handling."""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator,TransformerMixin
from sklearn.utils.validation import check_is_fitted
import copy

def nominal(name):
    return name=='current_state_id' or name.startswith('current_state_id_lag')

class FoldPreprocessor(TransformerMixin,BaseEstimator):
    def fit(self,X,y=None):
        if not isinstance(X,pd.DataFrame) or not X.columns.is_unique:raise ValueError('Named unique feature columns required')
        self.feature_names_in_=np.asarray(X.columns,dtype=object)
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
        self.output_names_=np.asarray(names,dtype=object);return self

    def transform(self,X):
        check_is_fitted(self,'output_names_')
        if list(X.columns)!=list(self.feature_names_in_):raise ValueError('Validation/test input column order differs from training')
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
        p=copy.copy(self);p.feature_names_in_=np.asarray(columns,dtype=object)
        for name in ['categorical_','numeric_','all_empty_','constant_','retained_']:
            setattr(p,name,[c for c in getattr(self,name) if c in columns])
        p.median_=self.median_.reindex(p.retained_);p.scale_=self.scale_.reindex(p.retained_)
        p.categories_={c:self.categories_[c] for c in p.categorical_}
        names=p.retained_+['missing__'+c for c in p.numeric_]
        for c,values in p.categories_.items():names += [c+'=='+str(v) for v in values]+[c+'==MISSING',c+'==UNSEEN']
        p.output_names_=np.asarray(names,dtype=object);return p
