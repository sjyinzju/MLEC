import ast
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.market_state.common import *
from scripts.market_state.measure import price_measure, average_correlation, window_measure
from scripts.market_state.dictionary import training_rows, fit_transform, apply_dictionary
from scripts.market_state.framework import load_dataset,preprocessing,paired_losses,load_universe
from scripts.market_state.macro import align

def test_price_arithmetic_and_anchor():
    q=price_measure([100,80,90])
    assert q['return']==pytest.approx(-.1)
    assert q['drawdown']==pytest.approx(.2)
    assert q['volatility']==pytest.approx(np.sqrt(126*(np.log(.8)**2+np.log(90/80)**2)))
    assert np.isnan(price_measure([100,np.nan,90])['drawdown'])

def test_correlation_aggregate_matches_dense_and_never_zero_fills():
    x=np.array([[1,4,2,np.nan],[2,3,3,1],[4,1,5,2],[3,2,4,3]],float)
    value,n=average_correlation(x)
    expected=np.corrcoef(x[:,:3].T)[np.triu_indices(3,1)].mean()
    assert n==3 and value==pytest.approx(expected)

def test_liquidity_order_and_units():
    # Cross-section median THEN time mean differs from pooling all stock-days.
    d=pd.DataFrame({c:[1.,1.] for c in ['amihud','turnover','breadth','return_dispersion','amount_cny','quote_coverage','return_coverage','float_coverage','suspension_fraction','unexplained_unquoted_fraction']})
    d['amihud']=[np.median([.1/100,.3/100,.9/100]),np.median([.2/100,.8/100])]
    d['members']=3;d['return_stocks']=2
    result=window_measure([100,99,101],d,np.array([[.1,.2],[.2,.1]]),np.ones((2,2),bool))
    assert result['amihud']==pytest.approx((.003+.005)/2)

def test_future_mutation_cannot_change_market_inputs(monkeypatch):
    from scripts.market_state import framework
    actual=read('market_features');future=read('future_window_outcomes').copy()
    future.loc[future.measurement_valid,CORE]=np.abs(future.loc[future.measurement_valid,CORE])*2+.001
    captured={};original_read=framework.read
    monkeypatch.setattr(framework,'read',lambda name:future if name=='future_window_outcomes' else original_read(name))
    monkeypatch.setattr(framework,'frame',lambda name,value:captured.update({name:value}))
    monkeypatch.setattr(framework,'write',lambda *args:None)
    framework.build_framework(joblib.load(OUT/'state_dictionary/dictionary.joblib'))
    pd.testing.assert_frame_equal(actual,captured['market_features'])

def test_no_post2019_dictionary_information():
    f=read('future_window_outcomes');changed=f.copy();changed.loc[changed.asof_date.dt.year.ge(2020),CORE]=123
    pd.testing.assert_frame_equal(training_rows(f),training_rows(changed))
    a=joblib.load(OUT/'state_dictionary/dictionary.joblib')
    assert a['transform']==fit_transform(training_rows(f))
    counts=training_rows(f).market_id.value_counts();assert counts.nunique()==1

def test_fixed_dictionary_does_not_change_past():
    p=read('past_window_outcomes');a=joblib.load(OUT/'state_dictionary/dictionary.joblib')
    first=p[p.asof_date.lt('2020')&p.window_length.eq(20)]
    before=apply_dictionary(first,a,'current')
    future=p.copy();future.loc[future.asof_date.ge('2020'),CORE]=999
    after=apply_dictionary(future[future.asof_date.lt('2020')&future.window_length.eq(20)],a,'current')
    pd.testing.assert_frame_equal(before,after)

@pytest.mark.parametrize('task',['classification','probability','regression'])
@pytest.mark.parametrize('role,fold',[('train','2020-01'),('validation','2020-01'),('train','2023-01'),('test','2023-01')])
def test_paired_rows_before_training(task,role,fold):
    a=load_dataset(information_set='M',task=task,fold_id=fold,role=role)
    b=load_dataset(information_set='M+Z',task=task,fold_id=fold,role=role)
    pd.testing.assert_frame_equal(a.metadata,b.metadata);pd.testing.assert_frame_equal(a.y,b.y)
    assert len(a.X)>0
    if role=='train':assert a.metadata.label_available_at.le(a.metadata.fit_cutoff).all()

def test_classes_probabilities_version_and_missing_tail():
    t=read('supervised_targets');valid=t.measurement_valid;q=[c for c in t if c.startswith('future_state_prob_')]
    assert t.loc[~valid,'future_state_id'].isna().all()
    assert np.allclose(t.loc[valid,q].sum(axis=1),1)
    assert (t.loc[valid,'future_state_id'].astype(int).to_numpy()==t.loc[valid,q].to_numpy().argmax(axis=1)).all()
    assert len(t.label_version.unique())==1
    assert set(t.market_id)==set(MARKETS)

def test_macro_scope_and_available_time():
    lin=read('macro/historical_reconstructed/lineage');valid=lin.available_at.notna()
    assert lin.loc[valid,'available_at'].le(lin.loc[valid,'asof_time']).all()
    f=read('macro/historical_reconstructed/features').set_index('asof_date')
    for r in lin[lin.change_scope_break|lin.change_ytd_reset|lin.change_period_gap].itertuples():
        assert pd.isna(f.loc[r.asof_date,f'macro__{r.series_id}__change'])
    assert any('change_20obs' in c for c in f)
    last=lin[lin.asof_date.eq(lin.asof_date.max())&lin.series_id.isin(['shibor_1w','cgb_10y'])]
    assert last.period_end.ge('2026-11-01').all()
    assert last.status.eq('AVAILABLE').all()
    assert lin[lin.series_id.eq('m1_yoy')&lin.asof_date.ge('2026')].status.eq('NOT_APPLICABLE').all()

def test_preprocessor_unfitted_and_missing_does_not_filter():
    pre=preprocessing();assert not hasattr(pre[0],'statistics_')
    m=load_dataset(information_set='M');z=load_dataset(information_set='M+Z')
    assert len(m.X)==len(z.X) and z.X.isna().any().any()

def test_future_generic_evaluation_contracts():
    from scripts.market_state.evaluation import multiclass_losses,continuous_losses,block_interval
    scores=multiclass_losses([0,2],[[.8,.1,.1],[.1,.2,.7]],[0,1,2])
    assert scores.brier.iloc[0]==pytest.approx(.06)
    assert continuous_losses([[1,2]],[[2,4]])['squared_error'].tolist()==[[1,4]]
    with pytest.raises(ValueError):multiclass_losses([0],[[.3,.3,.3]],[0,1,2])
    result=block_interval([1,2,3,4],pd.date_range('2020-01-03',periods=4,freq='7D'),repetitions=20)
    assert result['mean']==2.5

def test_calendar_and_boundary():
    t=read('supervised_targets');dates=pd.DatetimeIndex(read('calendar').date)
    for r in t[t.measurement_valid].itertuples():
        assert dates.get_loc(r.label_end)-dates.get_loc(r.asof_date)==20
        assert r.label_available_at==clock(r.label_end)
    fold=read('fold_membership').merge(t[KEY+['label_available_at']],on=KEY)
    assert fold.loc[fold.role.eq('validation'),'label_available_at'].le(clock('2022-12-31')).all()
    calendar=pd.read_parquet(OUT/'sources/trade_calendar.parquet')
    expected=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_open.astype(str).eq('1'),'cal_date']))
    expected=expected[(expected>=dates.min())&(expected<=dates.max())].sort_values().unique()
    assert dates.equals(expected)

def test_identity_no_survivor_or_pre_BSE_backfill():
    f=read('security_history');assert f[f.ts_code.str.endswith('.BJ')].valid_from.ge('2021-11-15').all()
    assert f.valid_to.lt('2026').any()
    changed=read('bse_code_changes');assert len(changed)>200
    assert changed.effective_date.eq('2025-05-06').sum()==6
    for market in MARKETS:
        f=load_universe(market,'2026-11-13')
        assert f.valid_from.le('2026-11-13').all() and f.valid_to.gt('2026-11-13').all()
        assert not f.instrument_id.duplicated().any()

def test_source_imports_no_retired_modules():
    for p in (ROOT/'scripts').rglob('*.py'):
        tree=ast.parse(p.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.module and node.module.startswith('scripts.'):
                target=ROOT/Path(*node.module.split('.'))
                assert target.is_dir() or target.with_suffix('.py').exists(),(p,node.module)
    for folder in ['scripts','config']:
        for p in (ROOT/folder).rglob('*'):
            if p.suffix in ['.py','.json']:
                content=p.read_text(encoding='utf8')
                assert not any(s in content for s in ['y_new_episode','episode_active','feature_whitelist','data/research_v2/']),p
