"""Explicit reproduction of the three original training-only calibration failures."""
import argparse
import importlib.util
from pathlib import Path
import numpy as np
from ..common import ROOT
from ..framework import DataStore,load_dataset
from ..model_contract import fit_inputs,fit_context,transform_inputs
from ..target_adapters import fit_targets
from ..models import rbf_svm
from ..models.training import TrainingPartitions
from ..models.svm_quality import array_state
from .artifacts import atomic_json,read_json
from .config import load_config
from .technical import scenarios
from .runtime import environment,experiment_code_hash
from ..release import file_hash


def decimal_local_evidence(parameters,x,target):
    """Independent 60-digit sum, Hessian and full Newton-direction objective."""
    from decimal import Decimal,localcontext
    with localcontext() as context:
        context.prec=60
        D=lambda v:Decimal.from_float(float(v))
        a,b=map(D,parameters);pairs=[(D(v),D(t)) for v,t in zip(x,target)]
        def objective(c,d):
            total=Decimal(0)
            for v,t in pairs:
                z=c*v+d
                total+=(1+z.exp()).ln()-t*z
            return total
        g0=g1=h00=h01=h11=Decimal(0)
        for v,t in pairs:
            p=1/(1+(-(a*v+b)).exp());w=p*(1-p);r=p-t
            g0+=r*v;g1+=r;h00+=w*v*v;h01+=w*v;h11+=w
        determinant=h00*h11-h01*h01
        if determinant<=0:return dict(positive_definite=False)
        da=-(h11*g0-h01*g1)/determinant;db=-(-h01*g0+h00*g1)/determinant
        objective0=objective(a,b);change=objective(a+da,b+db)-objective0
        largest=(h00+h11+((h00-h11)**2+4*h01*h01).sqrt())/2
        decrement=-(g0*da+g1*db)/2
        resolution=D(np.finfo(float).eps)*max(Decimal(1),abs(objective0))
        return dict(precision=60,positive_definite=True,objective=str(objective0),
            gradient_max=str(max(abs(g0),abs(g1))),hessian_condition=str(largest*largest/determinant),
            newton_decrement=str(decrement),newton_objective_change=str(change),
            objective_resolution=str(resolution),negligible_descent=bool(decrement<=8*resolution and change>=-8*resolution))


def reproduce(execute=False,old_root=None,destination=None,current=False):
    if not execute:raise ValueError('Explicit --execute needed')
    old=Path(old_root)
    spec=importlib.util.spec_from_file_location('scripts.market_state.models._original_sigmoid',old/'scripts/market_state/models/calibration.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=rbf_svm.TimeSigmoid
    implementation=original if current else module.TimeSigmoid
    captured={}
    class Capture(implementation):
        def fit(self,scores,labels,ids):
            captured.update(score_hash=array_state(scores),label_hash=array_state(labels),class_counts=np.bincount(labels,minlength=len(ids)).tolist())
            try:
                result=super().fit(scores,labels,ids)
                p=result.predict_proba(scores)
                captured['probabilities']=dict(finite=bool(np.isfinite(p).all()),normalization_error=float(abs(p.sum(axis=1)-1).max()),minimum=float(p.min()),maximum=float(p.max()))
                return result
            finally:
                audits=[]
                for j,r in enumerate(self.diagnostics_):
                    if 'slope' not in r:continue
                    n=int((labels==ids[j]).sum());negative=len(labels)-n
                    target=np.where(labels==ids[j],(n+1.)/(n+2.),1./(negative+2.))
                    audits.append(dict(class_id=int(ids[j]),**decimal_local_evidence([r['slope'],r['intercept']],scores[:,j]/r['score_scale'],target)))
                captured['independent_decimal']=audits
    c=load_config(ROOT/'config/experiments/rbf_svm.yaml');store=DataStore();rows=[]
    rules=c['calibration'] if current else read_json(old/'config/experiments/rbf_svm.yaml')['calibration']
    try:
        rbf_svm.TimeSigmoid=Capture
        for design in scenarios(True,'rbf_svm')[:3]:
            captured.clear()
            d=load_dataset(market_id=design['market'],information_set=design['information'],fold_id=design['fold'],task='classification',role='train',store=store)
            pre,t=fit_inputs(d),fit_targets(d)
            m=rbf_svm.RBFSVMAdapter(task='classification',preprocessor=pre,target_adapter=t,training_keys=d.keys,
                parameters=design['parameters'],seed=3060,policy=c['policy'],solver=c['solver'],calibration=rules,training_service=TrainingPartitions(d))
            row=dict(design=design,purpose='SMOKE_ONLY')
            try:
                m.fit(transform_inputs(pre,d),t.transform(d.y),fit_context(d));row['status']='PASSED'
            except Exception as error:row.update(status='FAILED',error=str(error),diagnostics=getattr(error,'diagnostics',[]))
            row.update(captured,calibration_plan=m.calibration_plan_)
            if row['status']=='PASSED':row['diagnostics']=m.diagnostics_
            rows.append(row)
            print(design['fold'],row['status'],flush=True)
    finally:rbf_svm.TimeSigmoid=original
    result=dict(purpose='SMOKE_ONLY',formal_BC=False,original_implementation_reproduction=not current,rows=rows,
        environment=environment(),experiment_code_hash=experiment_code_hash(),
        calibration_source_sha256=file_hash(ROOT/'scripts/market_state/models/calibration.py' if current else old/'scripts/market_state/models/calibration.py'))
    atomic_json(destination or ROOT/('reports/model_build/rbf_svm/repair_20261121/reproduction_'+('after' if current else 'before')+'.json'),result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--current',action='store_true');p.add_argument('--old-root',required=True);p.add_argument('--destination');reproduce(**vars(p.parse_args()))
