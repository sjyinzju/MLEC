"""Train-fold target format adaptation, independent of the GMM label transform."""
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .common import CORE, digest
from .model_contract import (CONTRACT_VERSION,DIMENSIONS,target_schema,target_context,truth_hash,
                             validate_probabilities,fit_context)


class TargetAdapter:
    def __init__(self,schema=None):
        self.schema_=schema or target_schema()

    def _begin(self,y,context):
        if truth_hash(y)!=context.training_target_hash:raise ValueError('Target differs from selected training cohort')
        if context.versions['dictionary_version']!=self.schema_['dictionary_version']:raise ValueError('Target dictionary version mismatch')
        self.context_=target_context(context)

    def _finish(self):
        self.adapter_version_=digest(self.record())
        return self

    def _fitted(self):
        if not hasattr(self,'adapter_version_'):raise ValueError('Target adapter is not fitted')

    def check_context(self,context):
        self._fitted()
        d=asdict(context) if not isinstance(context,dict) else context
        for k,v in self.context_.items():
            if k=='training_target_hash':continue  # input preprocessing has no dependency on y values
            if d.get(k)!=v:raise ValueError('Target adapter fit context mismatch: '+k)

    def record(self):
        return dict(kind=type(self).__name__,contract_version=CONTRACT_VERSION,schema=self.schema_,context=self.context_,parameters=self.parameters_)

    def save(self,path):
        self._fitted();p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(dict(self.record(),adapter_version=self.adapter_version_),ensure_ascii=False,indent=2),encoding='utf8')

    @classmethod
    def load(cls,path,*,context=None):
        r=json.loads(Path(path).read_text(encoding='utf8'));version=r.pop('adapter_version')
        if digest(r)!=version or r['contract_version']!=CONTRACT_VERSION:raise ValueError('Target artifact identity mismatch')
        kinds={'ClassificationTargetAdapter':ClassificationTargetAdapter,'RegressionTargetAdapter':RegressionTargetAdapter}
        if r['kind'] not in kinds:raise ValueError('Unknown target adapter')
        obj=kinds[r['kind']](r['schema']);obj.context_=r['context'];obj.parameters_=r['parameters'];obj.adapter_version_=version
        if context is not None:obj.check_context(context)
        return obj


class ClassificationTargetAdapter(TargetAdapter):
    def fit(self,y,context):
        self._begin(y,context)
        ids=self.schema_['class_ids'];a=self._values(y)
        self.parameters_=dict(research_to_internal={str(c):i for i,c in enumerate(ids)},internal_to_research=ids,
            observed_classes=[c for c in ids if c in a],missing_classes=[c for c in ids if c not in a],
            missing_class_policy='future estimator must declare handling before fit; never infer from held-out labels')
        return self._finish()

    def _values(self,y):
        if not isinstance(y,pd.DataFrame) or list(y.columns)!=['future_state_id']:raise ValueError('Classification requires one hard-label column')
        a=y.future_state_id.to_numpy()
        if pd.isna(a).any() or not set(a)<=set(self.schema_['class_ids']):raise ValueError('Unknown or missing class')
        return a

    def transform(self,y):
        self._fitted();return np.array([self.parameters_['research_to_internal'][str(int(c))] for c in self._values(y)],dtype=np.int64)

    def inverse_transform(self,values):
        self._fitted();a=np.asarray(values)
        ids=self.parameters_['internal_to_research']
        if a.ndim!=1 or not np.isin(a,np.arange(len(ids))).all():raise ValueError('Unknown internal class')
        return np.asarray(ids,dtype=np.int64)[a.astype(int)]

    def align_probabilities(self,probabilities,model_classes,*,class_space='internal',missing_policy):
        """Only explicit zero_for_absent can add missing columns; no renormalization."""
        self._fitted();classes=list(model_classes);p=np.asarray(probabilities,float)
        if len(set(classes))!=len(classes) or p.ndim!=2 or p.shape[1]!=len(classes):raise ValueError('Invalid model class columns')
        if class_space=='internal':research=self.inverse_transform(classes).tolist()
        elif class_space=='research':
            research=classes
            if not set(research)<=set(self.schema_['class_ids']):raise ValueError('Unknown research class')
        else:raise ValueError('Unknown class space')
        ids=self.schema_['class_ids']
        if missing_policy not in ['error','zero_for_absent']:raise ValueError('Declare missing-class probability policy')
        if set(research)!=set(ids) and missing_policy=='error':raise ValueError('Model is missing dictionary classes')
        validate_probabilities(p,research)
        result=np.zeros((len(p),len(ids)))
        for j,c in enumerate(research):result[:,ids.index(c)]=p[:,j]
        return validate_probabilities(result,ids)


class RegressionTargetAdapter(TargetAdapter):
    def _values(self,y):
        if not isinstance(y,pd.DataFrame) or list(y.columns)!=CORE:raise ValueError('Fixed ordered seven-target DataFrame required')
        a=y.to_numpy(float)
        if not np.isfinite(a).all():raise ValueError('Non-finite regression targets')
        return a

    def fit(self,y,context):
        self._begin(y,context);a=self._values(y)
        center=np.median(a,axis=0);iqr=np.quantile(a,.75,axis=0)-np.quantile(a,.25,axis=0)
        # Rescale deviations first: valid tiny targets must not underflow to constants.
        deviations=a-center;amplitude=np.max(np.abs(deviations),axis=0)
        scaled=np.divide(deviations,amplitude,out=np.zeros_like(a),where=amplitude>0)
        std=np.std(scaled,axis=0,ddof=0)*amplitude
        scale=np.where(iqr>0,iqr,np.where(std>0,std,1.))
        weight=np.array([1/np.sqrt(len(v)) for c in CORE for v in [next(v for v in DIMENSIONS.values() if c in v)]])
        self.parameters_=dict(center=center.tolist(),scale=scale.tolist(),weight=weight.tolist(),
            constant=(amplitude==0).tolist(),scale_method=['IQR' if q>0 else 'STD' if s>0 else 'ONE_CONSTANT' for q,s in zip(iqr,std)],
            formula='(original - train median) / train scale / sqrt(indicators in dimension)')
        return self._finish()

    def transform(self,y):
        self._fitted();p=self.parameters_
        return (self._values(y)-np.array(p['center']))/np.array(p['scale'])*np.array(p['weight'])

    def inverse_transform(self,values):
        self._fitted();a=np.asarray(values,float);p=self.parameters_
        if a.ndim!=2 or a.shape[1]!=len(CORE) or not np.isfinite(a).all():raise ValueError('Invalid transformed regression shape/values')
        return pd.DataFrame(a/np.array(p['weight'])*np.array(p['scale'])+np.array(p['center']),columns=CORE)


def fit_targets(ds):
    ctx=fit_context(ds)
    columns=list(ds.y.columns)
    if columns==['future_state_id']:return ClassificationTargetAdapter(ds.target_schema).fit(ds.y,ctx)
    if columns==CORE:return RegressionTargetAdapter(ds.target_schema).fit(ds.y,ctx)
    raise ValueError('Auxiliary soft memberships are not an automatic main training task')


def evaluation_scale(*,market_id,store):
    """Fixed initial-mature-training per-market evaluation scale, never monthly refit."""
    from .framework import load_dataset
    ds=load_dataset(market_id=market_id,task='regression',fold_id='initial',role='train',store=store)
    adapter=fit_targets(ds)
    return dict(version=digest(dict(purpose='fixed_evaluation_scale',context=adapter.context_,scale=adapter.parameters_['scale'])),
        market_id=market_id,source_fold='initial',fit_cutoff=adapter.context_['fit_cutoff'],
        versions=ds.versions,columns=CORE,scale=adapter.parameters_['scale'],dimensions=DIMENSIONS,
        aggregation='original-unit errors / fixed initial scale; mean within dimension then mean of five dimensions')
