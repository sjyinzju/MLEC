"""Read/transform/geometry audit only. No estimator or calibration fitting."""
from argparse import ArgumentParser
import numpy as np
from ..common import ROOT
from ..framework import DataStore,load_dataset,information_view
from ..model_contract import fit_inputs,transform_inputs,key_hash
from ..preprocessing import input_diagnostics,PREPROCESSING_VERSION
from ..models.training import TrainingPartitions
from ..models.rbf_svm import relative_gamma
from ..models.svm_quality import kernel_geometry
from .config import load_config,candidates
from .runtime import calibration_plans,preview
from .artifacts import atomic_json


def audit(destination=None,data_root=None):
    c=load_config(ROOT/'config/experiments/rbf_svm.yaml');store=DataStore(data_root)
    scans=[]
    for market in c['markets']:
        for fold in ['2020-01','2021-10','2022-12']:
            full=load_dataset(market_id=market,fold_id=fold,role='train',information_set='M+Z',store=store)
            paired=[]
            for info in ['M','M+Z']:
                d=information_view(full,info,store=store);pre=fit_inputs(d);x=transform_inputs(pre,d)
                pred=load_dataset(market_id=market,fold_id=fold,role='prediction',information_set=info,store=store)
                xp=transform_inputs(pre,pred)
                paired.append(x)
                scans.append(dict(market=market,fold=fold,information=info,training_keys_hash=key_hash(d.keys),
                    train=input_diagnostics(x),prediction=input_diagnostics(xp),
                    raw_max_abs=float(np.nanmax(np.abs(d.X.to_numpy()))),
                    columns={col:dict(variance=float(x[col].var(ddof=0)),min=float(x[col].min()),max=float(x[col].max())) for col in x},
                    removed=dict(all_empty=pre.all_empty_,constant=pre.constant_,near_constant=pre.near_constant_),
                    schema=pre.schema_['schema_version'],
                    kernels={str(f):kernel_geometry(x,relative_gamma(x,f)) for f in c['search']['gamma_factors']}))
            np.testing.assert_array_equal(paired[0],paired[1][paired[0].columns])
    supports=[]
    for row in calibration_plans(c,store):
        d=load_dataset(market_id=row['market_id'],fold_id=row['fold_id'],role='train',information_set='M',store=store)
        service=TrainingPartitions(d)
        supports.append(dict(market=row['market_id'],fold=row['fold_id'],blocks=row['blocks'],**service.support_summary(row['blocks'])))
    plans={suite:preview(c,store,suite)['budgets'] for suite in ['core','full']}
    coverage={}
    for task in c['tasks']:
        values=candidates(c,task)
        table=np.zeros((6,5),dtype=int)
        for v in values:
            p=v['parameters'];i=min(5,int((np.log10(p['C'])+3)//1));j=c['search']['gamma_factors'].index(p['gamma_factor']);table[i,j]+=1
        coverage[task]=dict(candidates=values,C_decade_by_gamma=table.tolist(),empty_cells=int((table==0).sum()),
            interpretation='Finite 48-point design, not exhaustive joint grid; kept unchanged without development search evidence')
    result=dict(purpose='NON_TRAINING_AUDIT',preprocessing=PREPROCESSING_VERSION,scans=scans,paired_financial_columns_exact=True,
        calibration_support=supports,plans=plans,coverage=coverage,estimator_fit_calls=0,calibration_optimization_calls=0,
        no_test_scores_read=True)
    atomic_json(destination or ROOT/'reports/model_build/rbf_svm/optimization_20261120/nontraining_audit.json',result)
    print('NON_TRAINING_AUDIT_PASSED',len(scans),'input views',len(supports),'outer cohorts; model fits=0')
    return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('--destination');p.add_argument('--data-root');audit(**vars(p.parse_args()))
