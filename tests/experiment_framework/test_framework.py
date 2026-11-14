import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'.local_deps'))
import numpy as np
import pandas as pd
import pytest
from scripts.macro_pipeline.govern import parse_title,parse_loan,validate_facts
from scripts.experiment_framework.dataset import asof_features,load_dataset
from scripts.experiment_framework.models import RiskModel,temporal_splits
from scripts.experiment_framework.evaluation import probability_metrics,paired_compare,choose_threshold,event_evaluate,block_interval
from scripts.experiment_framework.common import read_json

def fixture_facts():
    return pd.DataFrame({'series_id':['cpi_yoy']*3,'period_start':pd.to_datetime(['2019-11-01','2019-12-01','2019-11-01']),
        'period_end':pd.to_datetime(['2019-11-30','2019-12-31','2019-11-30']),
        'research_available_at':pd.to_datetime(['2019-12-10','2020-01-10','2020-01-12']).tz_localize('Asia/Shanghai'),
        'vintage_id':['a','b','c'],'source_record_id':['a','b','c'],'quality_status':['strict_pit_eligible']*3,
        'frequency':['M']*3,'value':[1.,2.,99.]})

def samples(dates=('2020-01-11','2020-01-18')):
    return pd.DataFrame({'sample_id':[str(i) for i in range(len(dates))],'asof_time':pd.to_datetime(list(dates)).tz_localize('Asia/Shanghai')})

def test_monthly_and_ytd_semantics():
    a=parse_title('2022年1—4月份规模以上工业增加值增长4.0%')
    b=parse_title('2022年4月份规模以上工业增加值下降2.9%')
    assert a['series_id']=='industrial_va_ytd_yoy' and a['value']==4
    assert b['series_id']=='industrial_va_yoy' and b['value']==-2.9
    assert a['period_start']==pd.Timestamp('2022-01-01')

def test_negative_retail_recovered():
    a=parse_title('2022年1—4月份社会消费品零售总额下降0.2%')
    assert a['value']==-.2 and a['measure_type']=='ytd_yoy'

def test_loan_cumulative_never_monthly():
    assert parse_loan('前八个月人民币贷款增加13.46万亿元')==134600
    assert parse_loan('8月份人民币贷款增加1000亿元') is None
    assert parse_loan('人民币贷款余额200万亿元') is None

def test_revision_of_old_period_does_not_replace_new_period():
    x,_=asof_features(fixture_facts(),samples(),['cpi_yoy'])
    assert x['z__cpi_yoy__latest'].tolist()==[2.,2.]
    assert x['z__cpi_yoy__previous'].tolist()==[1.,99.]

def test_historical_truncation_and_future_perturbation():
    f=fixture_facts();s=samples();a,_=asof_features(f,s,['cpi_yoy'])
    truncated=f[f.research_available_at<=s.asof_time.iloc[0]]
    b,_=asof_features(truncated,s.iloc[:1],['cpi_yoy'])
    pd.testing.assert_frame_equal(a.iloc[:1],b)
    f.loc[2,'value']=-10000
    c,_=asof_features(f,s.iloc[:1],['cpi_yoy']);pd.testing.assert_frame_equal(b,c)

def test_release_perturbation_only_after_availability():
    f=fixture_facts();s=samples();a,_=asof_features(f,s,['cpi_yoy'])
    f.loc[1,'research_available_at']=pd.Timestamp('2020-01-15',tz='Asia/Shanghai')
    b,_=asof_features(f,s,['cpi_yoy'])
    assert a.iloc[0]['z__cpi_yoy__latest']==2 and b.iloc[0]['z__cpi_yoy__latest']==1
    assert a.iloc[1]['z__cpi_yoy__latest']==b.iloc[1]['z__cpi_yoy__latest']

def test_unknown_quality_is_not_accepted():
    f=fixture_facts();f['quality_status']='latest_vintage_reconstructed'
    x,a=asof_features(f,samples(),['cpi_yoy']);assert x.filter(like='z__').isna().all().all()
    assert a.exclusion_reason.eq('no_eligible_history').all()

def test_staleness_blocks_old_observation():
    x,a=asof_features(fixture_facts(),samples(('2021-01-01',)),['cpi_yoy'])
    assert pd.isna(x['z__cpi_yoy__latest'].iloc[0]);assert a.exclusion_reason.iloc[0]=='stale_observation'

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

def prediction_fixture():
    s=samples(('2020-01-03','2020-01-10','2021-01-08','2021-01-15'))
    return s.assign(fold_id=['dev-2020']*2+['dev-2021']*2,horizon=20,y_true=[1,1,0,0],predicted_probability=[.8,.9,.7,.1],fit_cutoff='2019',sample_version='main_v1',protocol_hash='x')

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

@pytest.mark.parametrize('fold',['dev-2020','dev-2021','dev-2022'])
def test_real_loader_maturity_white_list_and_final_isolation(fold):
    d=load_dataset('main_v1','M',20,fold,'train')
    assert d.metadata.label_available_at.le(d.metadata.fit_cutoff).all()
    assert not any(c.startswith(('future_','y_')) for c in d.X)
    for train,valid,cutoff in temporal_splits(d.metadata):
        assert d.metadata.iloc[train].label_available_at.le(cutoff).all()
        assert d.metadata.iloc[valid].asof_time.gt(cutoff).all()
    with pytest.raises(ValueError):load_dataset('main_v1','M',20,'final-2023-01','train')
    with pytest.raises(ValueError):load_dataset('main_v1','M_plus_Z_core',20,fold,'train')
    for role in ['train','validation']:
        m=load_dataset('common_core_v1','M',20,fold,role)
        z=load_dataset('common_core_v1','M_plus_Z_core',20,fold,role)
        pd.testing.assert_frame_equal(m.metadata,z.metadata)
        pd.testing.assert_series_equal(m.y,z.y)
        assert len(z.feature_names)>len(m.feature_names)
        assert z.feature_availability.feature_available_at.notna().all()

def test_actual_macro_schema_lineage_daily_dates():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet');validate_facts(f)
    assert f.source_record_id.notna().all() and f.source_url.notna().all()
    rates=f[f.series_id.str.startswith('shibor')]
    assert rates.period_end.eq(rates.observation_date).all()
    assert rates.period_start.eq(rates.period_end).all()
    invalid=f[f.quality_status.eq('blocked')];assert len(invalid)>0
    assert not f[(f.series_id=='industrial_va_yoy')&(f.period_end==pd.Timestamp('2022-04-30'))].value.eq(4).any()

def test_actual_market_rebuild_and_future_price_perturbation():
    sys.path.insert(0,str(ROOT/'scripts/research_v2'))
    from core import observations,thresholds,states,all_events,build_weekly,temporal_folds,event_opportunities
    raw=pd.read_parquet(ROOT/'data/research_v2/market_daily_clean.parquet')
    original=pd.read_parquet(ROOT/'data/research_v2/market_observations_daily.parquet')
    rebuilt=observations(raw)
    pd.testing.assert_frame_equal(rebuilt,original,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    thr=read_json(ROOT/'config/research_v2/thresholds.json');s,e=all_events(rebuilt,states(rebuilt,thr))
    cal=pd.read_parquet(ROOT/'audit/research_v2/sse_calendar.parquet')
    f,o,t,m=build_weekly(rebuilt,s,e,cal,thr)
    for name,df in [('market_features_weekly',f),('prediction_targets_weekly',t),('sample_to_event',m)]:
        pd.testing.assert_frame_equal(df,pd.read_parquet(ROOT/f'data/research_v2/{name}.parquet'),check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    plan,membership=temporal_folds(f,t,cal)
    pd.testing.assert_frame_equal(membership,pd.read_parquet(ROOT/'data/research_v2/fold_membership.parquet'),check_dtype=False)
    cutoff=pd.Timestamp('2020-12-31');mutated=raw.copy();mutated.loc[mutated.date>cutoff,'close']*=2
    changed=observations(mutated)
    pd.testing.assert_frame_equal(rebuilt[rebuilt.date<=cutoff],changed[changed.date<=cutoff])
    truncated=observations(raw[raw.date<=cutoff].copy())
    pd.testing.assert_frame_equal(rebuilt[rebuilt.date<=cutoff],truncated)

def test_core_official_history_complete_and_crosscheck():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    a=f[f.quality_status.eq('strict_pit_eligible')]
    expected=set(pd.period_range('2014-12','2022-12',freq='M'))
    for sid in ['cpi_yoy','ppi_yoy','pmi_mfg','pmi_new_orders','m2_yoy']:
        assert expected<=set(a[a.series_id.eq(sid)].period_end.dt.to_period('M'))
    c=pd.read_parquet(ROOT/'audit/framework/macro_crosscheck.parquet')
    exact=c[c.series_id.isin(['cpi_yoy','ppi_yoy','pmi_mfg','pmi_new_orders'])]
    assert len(exact)>500 and exact.difference.abs().le(.051).all()

def test_actual_release_dates_and_semantic_regressions():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    a=f[f.quality_status.eq('strict_pit_eligible')]
    p=a[a.series_id.eq('pmi_mfg')&a.period_end.eq('2015-01-31')]
    assert p.release_at.dt.strftime('%Y-%m-%d').eq('2015-02-01').all()
    p=a[a.series_id.eq('pmi_mfg')&a.period_end.eq('2022-01-31')]
    assert p.release_at.dt.strftime('%Y-%m-%d').eq('2022-01-30').all()
    for sid,value in [('industrial_va_yoy',-2.9),('industrial_va_ytd_yoy',4.),('retail_sales_yoy',-11.1),('retail_sales_ytd_yoy',-.2)]:
        p=a[a.series_id.eq(sid)&a.period_end.eq('2022-04-30')]
        assert len(p) and np.allclose(p.value,value)
    assert not a[a.series_id.str.startswith('gdp_')].period_end.gt(a[a.series_id.str.startswith('gdp_')].release_at.dt.tz_localize(None)).any()
    original_gdp=f[f.original_series_id.eq('gdp_real_yoy')&f.source_name.str.contains('东方财富')]
    assert len(original_gdp)>0 and original_gdp.series_id.eq('gdp_real_ytd_yoy').all()
    assert not a[a.series_id.eq('m1_yoy')].period_end.ge('2025-01-01').any()
    assert f[f.source_url.str.contains('RPT_ECONOMY_RMB_LOAN',regex=False)].quality_status.eq('blocked').all()

def test_pmi_published_before_calendar_month_end_is_usable():
    f=fixture_facts().iloc[:1].copy()
    f['series_id']='pmi_mfg';f['period_start']=pd.Timestamp('2022-01-01');f['period_end']=pd.Timestamp('2022-01-31')
    f['research_available_at']=pd.Timestamp('2022-01-28 23:59:59',tz='Asia/Shanghai')
    x,_=asof_features(f,samples(['2022-01-29']),['pmi_mfg'])
    assert x['z__pmi_mfg__latest'].notna().all()

def test_all_missing_constant_input_falls_back_to_training_prior():
    x=pd.DataFrame({'a':[np.nan]*8,'b':[1]*8});y=pd.Series([0,0,0,0,0,0,1,1])
    for algorithm in ['logistic','random_forest','gradient_boosting']:
        m=RiskModel(algorithm).fit(x,y,{})
        np.testing.assert_allclose(m.predict_proba(x),.25)
        assert m.fallback_reason=='all_features_constant_or_missing'

def test_official_quote_units_and_date_integrity():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    d=f[f.quality_status.eq('conservative_release_reconstructed')]
    assert d.period_start.eq(d.period_end).all()
    assert d.research_available_at.dt.hour.eq(23).all()
    assert not d.duplicated(['series_id','period_end']).any()
    fx=d[d.series_id.eq('usdcny_fixing')&d.period_end.eq('2025-12-31')]
    assert len(fx)==1 and fx.value.iloc[0]==pytest.approx(7.0288)

def test_real_daily_windows_ignore_future_quotes_and_use_known_dates():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    f=f[f.series_id.eq('shibor_1w')&f.quality_status.eq('conservative_release_reconstructed')].copy()
    s=samples(['2020-02-07 18:00:00'])
    x,lineage=asof_features(f,s,['shibor_1w'],quality=('conservative_release_reconstructed',))
    known=f[f.research_available_at<=s.asof_time.iloc[0]].sort_values('period_end')
    assert x['z__shibor_1w__latest'].iloc[0]==known.value.iloc[-1]
    assert x['z__shibor_1w__mean_20d'].notna().all()
    f.loc[f.research_available_at>s.asof_time.iloc[0],'value']=99999.
    changed,_=asof_features(f,s,['shibor_1w'],quality=('conservative_release_reconstructed',))
    pd.testing.assert_frame_equal(x,changed)
    used=set(lineage.source_record_ids.iloc[0].split('|'))
    assert len(used)>=20 and used<=set(known.source_record_id)

def test_registered_ablations_keep_full_core_common_sample():
    r=read_json(ROOT/'config/experiments/feature_sets.json')
    for name,spec in r.items():
        if name.startswith('M_plus_Z_core_without_'):
            assert spec['sample_version']==r['M_plus_Z_core']['sample_version']=='common_core_v1'
            assert set(spec['series'])<set(r['M_plus_Z_core']['series'])
