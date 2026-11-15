"""Existing model/evaluation unit tests. Not executed during data-only repair.
Data/availability tests now live in test_v5_data_interface.py.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'.local_deps'))
import numpy as np
import pandas as pd
import pytest
from scripts.experiment_framework.models import RiskModel
from scripts.experiment_framework.evaluation import probability_metrics,paired_compare,choose_threshold,event_evaluate


def prediction_fixture():
    dates=['2020-01-03','2020-01-10','2021-01-08','2021-01-15']
    samples=pd.DataFrame({'sample_id':[str(i) for i in range(len(dates))],
        'asof_time':pd.to_datetime(dates).tz_localize('Asia/Shanghai')})
    return samples.assign(fold_id=['dev-2020']*2+['dev-2021']*2,horizon=20,
        y_true=[1,1,0,0],predicted_probability=[.8,.9,.7,.1],fit_cutoff='2019',
        sample_version='synthetic_unit_fixture',protocol_hash='x')


@pytest.mark.parametrize('algorithm,params',[
    ('historical_rate',{}),('logistic',{'C':.1,'penalty':'l2'}),
    ('random_forest',{'n_estimators':20,'max_depth':2,'min_samples_leaf':5}),
    ('gradient_boosting',{'n_estimators':20,'max_depth':1,'min_samples_leaf':5})])
@pytest.mark.parametrize('macro',[False,True])
def test_models_variable_features_save_load_seed(tmp_path,algorithm,params,macro):
    rng=np.random.default_rng(5);X=pd.DataFrame({'ret':rng.normal(size=80),'constant':1.,'state_id':['S0']*80})
    if macro:X['z__cpi']=rng.normal(size=80);X.loc[:8,'z__cpi']=np.nan
    y=pd.Series(([0]*5+[1]*3)*10)
    a=RiskModel(algorithm,params).fit(X,y,{'fit_cutoff':'2019-12-31'})
    b=RiskModel(algorithm,params).fit(X,y,{'fit_cutoff':'2019-12-31'})
    p=a.predict_proba(X);assert ((p>=0)&(p<=1)).all()
    np.testing.assert_array_equal(p,b.predict_proba(X))
    path=tmp_path/'m.joblib';a.save(path);np.testing.assert_array_equal(p,RiskModel.load(path).predict_proba(X))
    if algorithm!='historical_rate': assert 'constant' not in a.interpretation().feature.tolist()


def test_preprocess_fits_train_only():
    X=pd.DataFrame({'x':[1.,2.,3.,np.nan,5.,6.]*10,'state_id':['S0']*60});y=np.tile([0,1],30)
    m=RiskModel('logistic',{'C':1.}).fit(X,y,{})
    imputer=m.pipeline['preprocess']['columns'].named_transformers_['numeric']['impute']
    before=imputer.statistics_.copy();test=X.copy();test['x']=1e9;m.predict_proba(test)
    np.testing.assert_array_equal(before,imputer.statistics_);assert before[0]==3


def test_probability_metrics_hand_calculation():
    d=probability_metrics([0,1],[.25,.75]);assert d['brier']==pytest.approx(.0625);assert d['log_loss']==pytest.approx(-np.log(.75))
    assert probability_metrics([0,0],[.1,.2])['roc_auc'] is None
    with pytest.raises(ValueError):probability_metrics([0],[np.nan])


def test_paired_keys_and_calendar_uncertainty():
    p=prediction_fixture();d,ci=paired_compare(p,p);assert ci['mean']==0 and ci['lower']==0
    with pytest.raises(ValueError):paired_compare(p,p.iloc[:2])
    with pytest.raises(ValueError):paired_compare(p,pd.concat([p,p.iloc[:1]]))


def test_budget_per_year_and_final_lock():
    p=prediction_fixture();t=choose_threshold(p,0);assert t>.7
    p.loc[0,'asof_time']=pd.Timestamp('2024-01-01',tz='Asia/Shanghai')
    with pytest.raises(ValueError):choose_threshold(p,2)


def test_event_dedup_and_no_opportunities():
    p=prediction_fixture()
    ep=pd.DataFrame({'episode_id':['a','b'],'dimension':['combined']*2,'onset_date':pd.to_datetime(['2020-01-20','2021-02-01']),'full_20d_lead_window':[True,False]})
    mapping=pd.DataFrame({'sample_id':['0','1'],'dimension':['combined']*2,'horizon':[20]*2,'at_risk_at_prediction':[True]*2,'episode_id':['a']*2,'onset_date':pd.to_datetime(['2020-01-20']*2),'lead_to_trigger':[11,6],'current_drawdown_at_prediction':[.01,.02]})
    e,s=event_evaluate(p,ep,mapping,.5)
    assert s['detected_events']==1 and s['eligible_events']==1 and s['repeated_alarms']==1
    assert e.loc[e.episode_id.eq('b'),'eligible'].iloc[0]==False
    assert s['lead_mean']==11


def test_all_missing_constant_input_falls_back_to_training_prior():
    x=pd.DataFrame({'a':[np.nan]*8,'b':[1]*8});y=pd.Series([0,0,0,0,0,0,1,1])
    for algorithm in ['logistic','random_forest','gradient_boosting']:
        m=RiskModel(algorithm).fit(x,y,{})
        np.testing.assert_allclose(m.predict_proba(x),.25)
        assert m.fallback_reason=='all_features_constant_or_missing'
