"""Small CPU model registry with fold-local preprocessing and temporal selection."""
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
from sklearn.dummy import DummyClassifier
from sklearn.metrics import brier_score_loss

def preprocessing(X):
    cats=[c for c in X if c=='state_id' or not pd.api.types.is_numeric_dtype(X[c])]
    nums=[c for c in X if c not in cats]
    numeric=Pipeline([('impute',SimpleImputer(strategy='median',keep_empty_features=True)),('scale',StandardScaler())])
    categorical=Pipeline([('impute',SimpleImputer(strategy='most_frequent',keep_empty_features=True)),('onehot',OneHotEncoder(handle_unknown='ignore',sparse_output=False))])
    return Pipeline([('columns',ColumnTransformer([('numeric',numeric,nums),('categorical',categorical,cats)],verbose_feature_names_out=False)),('variance',VarianceThreshold())])

class RiskModel:
    def __init__(self,algorithm,params=None,seed=3059):
        self.algorithm=algorithm;self.params=params or {};self.seed=seed

    def fit(self,X_train,y_train,context):
        self.context=context;self.feature_names=list(X_train.columns)
        self.fallback_reason='single_class' if len(set(y_train))<2 else ('all_features_constant_or_missing' if X_train.nunique(dropna=True).le(1).all() else '')
        if self.fallback_reason or self.algorithm=='historical_rate':
            self.pipeline=Pipeline([('model',DummyClassifier(strategy='prior'))])
            self.pipeline.fit(np.zeros((len(X_train),1)),y_train);self.constant=True
        else:
            if self.algorithm=='logistic':
                params=self.params.copy()
                if 'penalty' in params: params['l1_ratio']=1. if params.pop('penalty')=='l1' else 0.
                estimator=LogisticRegression(solver='liblinear',max_iter=3000,random_state=self.seed,**params)
            elif self.algorithm=='random_forest': estimator=RandomForestClassifier(n_jobs=1,random_state=self.seed,**self.params)
            elif self.algorithm=='gradient_boosting': estimator=GradientBoostingClassifier(random_state=self.seed,**self.params)
            else: raise ValueError(self.algorithm)
            self.pipeline=Pipeline([('preprocess',preprocessing(X_train)),('model',estimator)])
            self.pipeline.fit(X_train,y_train);self.constant=False
        return self

    def predict_proba(self,X):
        if list(X.columns)!=self.feature_names: raise ValueError('Feature schema mismatch')
        p=self.pipeline.predict_proba(np.zeros((len(X),1)) if self.constant else X)
        classes=self.pipeline.named_steps['model'].classes_
        return p[:,list(classes).index(1)] if 1 in classes else np.zeros(len(X))

    def save(self,path): joblib.dump(self,path)

    @staticmethod
    def load(path): return joblib.load(path)

    def interpretation(self):
        if self.constant:return pd.DataFrame(columns=['feature','value','kind'])
        prep=self.pipeline.named_steps['preprocess']; model=self.pipeline.named_steps['model']
        names=prep[:-1].get_feature_names_out()[prep[-1].get_support()]
        values=model.coef_[0] if hasattr(model,'coef_') else model.feature_importances_
        return pd.DataFrame({'feature':names,'value':values,'kind':'coefficient' if hasattr(model,'coef_') else 'importance'})

def temporal_splits(metadata):
    """Expanding inner yearly folds, purged by actual full-label maturity."""
    years=sorted(metadata.asof_time.dt.year.unique())
    for year in years[-3:]:
        valid=np.flatnonzero(metadata.asof_time.dt.year.eq(year).to_numpy())
        if not len(valid):continue
        cutoff=pd.Timestamp(f'{year-1}-12-31 23:59:59',tz='Asia/Shanghai')
        train=np.flatnonzero((metadata.asof_time.lt(cutoff)&metadata.label_available_at.le(cutoff)).to_numpy())
        if len(train)>=40: yield train,valid,cutoff

def select_model(algorithm,grid,dataset,seed):
    evidence=[];candidates=[]
    for i,params in enumerate(grid):
        losses=[]
        for tr,va,cutoff in temporal_splits(dataset.metadata):
            assert dataset.metadata.iloc[tr].label_available_at.le(cutoff).all()
            m=RiskModel(algorithm,params,seed).fit(dataset.X.iloc[tr],dataset.y.iloc[tr],{'fit_cutoff':str(cutoff),'role':'inner'})
            p=m.predict_proba(dataset.X.iloc[va]);losses.extend((dataset.y.iloc[va].to_numpy()-p)**2)
            evidence.append({'candidate':i,'params':params,'cutoff':str(cutoff),'n_train':len(tr),'n_valid':len(va),'brier':brier_score_loss(dataset.y.iloc[va],p)})
        if not losses: raise ValueError('No legal temporal selection folds')
        candidates.append((float(np.mean(losses)),i,params))
    _,_,best=min(candidates,key=lambda x:(x[0],x[1]))
    # Selected-parameter inner OOF calibration stays inside outer training.
    # Hyperparameter selection reuses these inner folds; report that limitation.
    cal_y=[];cal_p=[]
    for tr,va,cutoff in temporal_splits(dataset.metadata):
        m=RiskModel(algorithm,best,seed).fit(dataset.X.iloc[tr],dataset.y.iloc[tr],{'fit_cutoff':str(cutoff)})
        cal_y.extend(dataset.y.iloc[va]);cal_p.extend(m.predict_proba(dataset.X.iloc[va]))
    calibrator=None
    if len(cal_y)>=30 and len(set(cal_y))==2 and algorithm!='historical_rate':
        calibrator=LogisticRegression(C=1.,solver='lbfgs',random_state=seed)
        calibrator.fit(logits(cal_p),cal_y)
    final=RiskModel(algorithm,best,seed).fit(dataset.X,dataset.y,{'fit_cutoff':str(dataset.fold_metadata['fit_cutoff']),'hashes':dataset.hashes,'seed':seed})
    return final,calibrator,evidence,best

def logits(p):
    p=np.clip(np.asarray(p),1e-6,1-1e-6);return np.log(p/(1-p)).reshape(-1,1)
