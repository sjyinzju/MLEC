"""Executed artifact checks, independent arithmetic replay and coverage audit."""
import joblib
import numpy as np
import pandas as pd
from .common import *
from .dictionary import training_rows,fit_transform,apply_dictionary
from .framework import load_dataset

def verify():
    checks={};f=read('future_window_outcomes');t=read('supervised_targets');m=read('sample_manifest');p=read('past_window_outcomes')
    for name in ['future_window_outcomes','supervised_targets','sample_manifest','market_features']:
        q=read(name);assert not q.duplicated(KEY).any();assert set(q.market_id)==set(MARKETS)
    checks['four_markets_unique_keys']=True
    conflict=pd.read_parquet(ROOT/'data/metadata/index_price_conflicts.parquet')
    quotes=read('index_prices').set_index(['ts_code','trade_date'])
    for r in conflict.itertuples():
        assert r.price_resolution=='PRIMARY_CONFIRMED_BY_INDEX_ADMINISTRATOR'
        assert abs(quotes.loc[(r.ts_code,r.trade_date),'close']-r.close)<=.00501
    checks['CSI1000_verified_source_conflicts_retained']=True
    assert f.groupby('asof_date').market_id.nunique().eq(4).all()
    assert f.groupby('market_id').asof_date.nunique().nunique()==1
    assert f.loc[f.measurement_valid,CORE].notna().all().all()
    assert t.loc[~f.measurement_valid,'future_state_id'].isna().all()
    cal=pd.DatetimeIndex(read('calendar').date)
    official=pd.read_parquet(OUT/'sources/trade_calendar.parquet')
    expected=pd.DatetimeIndex(pd.to_datetime(official.loc[official.exchange.eq('SSE')&official.is_open.astype(str).eq('1'),'cal_date']))
    expected=expected[(expected>=cal.min())&(expected<=cal.max())].sort_values().unique()
    assert expected.equals(cal)
    checks['calendar_matches_independent_exchange_open_dates']=True
    for r in f[f.measurement_valid].itertuples():
        assert cal.get_loc(r.label_start)==cal.get_loc(r.asof_date)+1
        assert cal.get_loc(r.label_end)==cal.get_loc(r.asof_date)+20
        assert r.label_available_at==clock(r.label_end)
    checks['full_20_day_windows_and_no_tail_fabrication']=True
    artifact=joblib.load(OUT/'state_dictionary/dictionary.joblib');params=fit_transform(training_rows(f))
    assert params==artifact['transform']
    changed=f.copy();changed.loc[changed.asof_date.dt.year.ge(2020),CORE]=999.
    pd.testing.assert_frame_equal(training_rows(changed),training_rows(f))
    checks['post2019_mutation_cannot_change_dictionary_fit_inputs']=True
    current=read('current_states');replay=apply_dictionary(p[p.window_length.eq(20)],artifact,'current')
    pd.testing.assert_frame_equal(replay.reset_index(drop=True),current)
    qcols=[c for c in t if c.startswith('future_state_prob_')]
    assert np.allclose(t.loc[t.future_state_id.notna(),qcols].sum(axis=1),1)
    assert t.loc[t.future_state_id.notna(),'future_state_id'].to_numpy().astype(int).tolist()==t.loc[t.future_state_id.notna(),qcols].to_numpy().argmax(axis=1).tolist()
    assert t.label_version.eq(current.label_version.iloc[0]).all()
    checks['shared_dictionary_current_future_probability_order']=True
    folds=read('fold_membership');joined=folds.merge(m,on=KEY,validate='many_to_one')
    assert joined.loc[joined.role.eq('train'),'label_available_at'].le(joined.loc[joined.role.eq('train'),'fit_cutoff']).all()
    assert joined.loc[joined.role.eq('validation'),'asof_date'].dt.year.between(2020,2022).all()
    assert joined.loc[joined.role.eq('validation'),'label_available_at'].le(clock('2022-12-31')).all()
    assert joined.loc[joined.role.eq('test'),'asof_date'].dt.year.ge(2023).all()
    checks['monthly_splits_mature_and_development_boundary_purged']=True
    for task in ['classification','probability','regression']:
        a=load_dataset(information_set='M',task=task,fold_id='2023-01',role='train')
        b=load_dataset(information_set='M+Z',task=task,fold_id='2023-01',role='train')
        pd.testing.assert_frame_equal(a.metadata,b.metadata);pd.testing.assert_frame_equal(a.y,b.y)
        assert not any('future' in c for c in a.X)
    checks['all_tasks_M_MZ_identical_training_and_targets']=True
    lin=read('macro/historical_reconstructed/lineage')
    assert lin.loc[lin.available_at.notna(),'available_at'].le(lin.loc[lin.available_at.notna(),'asof_time']).all()
    checks['macro_asof_clock']=True
    ids=read('security_history')
    assert ids[ids.ts_code.str.endswith('.BJ')].valid_from.ge('2021-11-15').all()
    assert not ids[['instrument_id','ts_code','valid_from']].duplicated().any()
    checks['historical_security_BSE_opening_and_aliases']=True
    # Independent raw-normalized arithmetic replay for a market/week, including
    # a dense correlation ONLY for 300 stocks in this one audit (never retained).
    example=f[f.market_id.eq('000300.SH')&f.asof_date.eq('2015-07-03')].iloc[0]
    i=cal.get_loc(example.asof_date);days=cal[i+1:i+21]
    prices=read('index_prices');prices=prices[prices.ts_code.eq(example.market_id)].set_index('date').close.reindex(cal[i:i+21]).to_numpy()
    r=np.log(prices[1:]/prices[:-1]);dd=max(1-prices[b]/prices[:b+1].max() for b in range(21))
    assert np.isclose(example['return'],prices[-1]/prices[0]-1)
    assert np.isclose(example.volatility,np.sqrt(252*np.sum(r*r)/20))
    assert np.isclose(example.drawdown,dd)
    stocks=pd.read_parquet(OUT/'cache/stocks/2015.parquet');w=read('membership_snapshots');w=w[w.index_code.eq(example.market_id)]
    code_ids=ids[['ts_code','instrument_id']].drop_duplicates().set_index('ts_code').instrument_id.to_dict()
    panels=[];daily=[]
    for day in days:
        snap=w[w.snapshot_date.le(day)].snapshot_date.max();codes=w.loc[w.snapshot_date.eq(snap),'con_code'];members={code_ids[c] for c in codes if c in code_ids}
        s=stocks[stocks.date.eq(day)&stocks.instrument_id.isin(members)].copy();s=s.set_index('instrument_id')
        good=s[s.r.notna()&s.amount_cny.gt(0)];cap=s[s.float_shares.gt(0)&s.volume_shares.notna()]
        daily.append([np.median(np.abs(good.r)/good.amount_cny),cap.volume_shares.sum()/cap.float_shares.sum(),(s.loc[s.r.notna(),'r']<0).mean()])
        panels.append(s.r.reindex(sorted(members)).rename(day))
    panel=pd.concat(panels,axis=1).T.dropna(axis=1);panel=panel.loc[:,panel.std()>0]
    corr=np.corrcoef(panel.to_numpy().T);pair=np.mean(corr[np.triu_indices(len(corr),1)])
    actual=np.mean(daily,axis=0)
    np.testing.assert_allclose([example.amihud,example.turnover,example.breadth],actual,rtol=1e-12)
    assert np.isclose(example.correlation,pair)
    checks['independent_seven_metric_raw_replay_20150703']=True
    REPORT.mkdir(parents=True,exist_ok=True)
    write(REPORT/'arithmetic_replay.json',dict(key={k:example[k] for k in KEY},price_path=prices.tolist(),daily_log_returns=r.tolist(),
        actual=dict(zip(CORE,[prices[-1]/prices[0]-1,np.sqrt(252*np.sum(r*r)/20),dd,*actual,pair])),balanced_stocks=len(corr)))
    write(REPORT/'validation.json',dict(checks=checks,all_passed=all(checks.values()),label_version=artifact['label_version']))
    return checks
