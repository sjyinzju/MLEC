"""Independent source arithmetic, full-domain checks, causal and cache audits."""
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .common import *
from .release import file_hash,cutoff,code_hash

def direct_window(market,asof,h=20,direction='future'):
    """Independent simple implementation. Never calls generation measures."""
    cal=pd.DatetimeIndex(read('calendar').date);i=cal.get_loc(pd.Timestamp(asof));a,b=(i,i+h) if direction=='future' else (i-h,i)
    dates=cal[a+1:b+1];anchor=cal[a]
    prices=read('index_prices');p=prices[prices.ts_code.eq(market)].set_index('date').close.reindex(cal[a:b+1]).to_numpy()
    lr=np.log(p[1:]/p[:-1]);loss=max(1-p[j]/max(p[:j+1]) for j in range(h+1))
    c=db();stock=c.execute("SELECT instrument_id,date,close,adj_factor,volume_shares,amount_cny,float_shares FROM read_parquet(?) WHERE date BETWEEN ? AND ?",[str(OUT/'cache/stocks/*.parquet'),anchor,cal[b]]).df();c.close()
    stocks={d:g.set_index('instrument_id') for d,g in stock.groupby('date')}
    ids=read('security_history');w=read('membership_snapshots');w=w[w.index_code.eq(market)]
    alias=ids[['ts_code','instrument_id']].drop_duplicates().set_index('ts_code').instrument_id.to_dict()
    daily=[];panels=[];sets=[];coverage=[]
    for j,day in enumerate(dates):
        active=ids[ids.valid_from.le(day)&ids.valid_to.gt(day)]
        if market=='000985.SH':active=active[active.security_type.eq('A_SHARE')]
        members=set(active.instrument_id)
        if market!='000985.SH':
            snap=w.loc[w.snapshot_date.le(day),'snapshot_date'].max()
            if pd.isna(snap) or (day-snap).days>45:members=set()
            else:members &= {alias[x] for x in w.loc[w.snapshot_date.eq(snap),'con_code'] if x in alias}
        sets.append(members)
        s=stocks.get(day,pd.DataFrame()).reindex(sorted(members)).copy()
        prev=stocks.get(cal[a+j],pd.DataFrame()).reindex(s.index)
        adjusted=np.log((s.close*s.adj_factor)/(prev.close*prev.adj_factor))
        adjusted=adjusted.where((s.volume_shares>0)&(prev.volume_shares>0))
        good=adjusted.notna()&s.amount_cny.gt(0)
        cap=s.float_shares.gt(0)&s.volume_shares.notna()
        daily.append([np.median(np.abs(adjusted[good])/s.loc[good,'amount_cny']),s.loc[cap,'volume_shares'].sum()/s.loc[cap,'float_shares'].sum(),(adjusted.dropna()<0).mean()])
        panels.append(adjusted.rename(day));coverage.append((len(members),int(adjusted.notna().sum())))
    common=set.intersection(*sets);x=pd.concat(panels,axis=1).T.reindex(columns=sorted(common)).dropna(axis=1).to_numpy(float)
    x=x[:,x.std(axis=0)>0];n=x.shape[1]
    # Sum actual pairwise dot products in small temporary blocks. This is
    # independent of generation's sum-of-standardized-returns formula.
    z=(x-x.mean(axis=0));z=z/np.sqrt((z*z).sum(axis=0));total=0.
    with threadpool_limits(limits=2):
        for start in range(0,n,128):total += (z[:,start:start+128].T@z).sum()
    corr=(total-n)/(n*(n-1)) if n>=2 else np.nan
    q=dict(zip(CORE,[p[-1]/p[0]-1,np.sqrt(252*np.mean(lr*lr)),loss,*np.mean(daily,axis=0),corr]))
    q.update(worst_cumulative_return=min(p[1:]/p[0]-1),correlation_stocks=n,correlation_union_stocks=len(set.union(*sets)),
        min_members=min(v[0] for v in coverage),min_return_stocks=min(v[1] for v in coverage))
    return q

def independent_replays():
    f=read('future_window_outcomes');past=read('past_window_outcomes');rows=[]
    # Broad market paths, annual handoffs, regular membership changes, BSE
    # opening/code changes, dividend dates and the provider handoff.
    requested=['2015-04-24','2015-07-03','2017-06-16','2019-12-27','2021-11-12','2025-05-02','2025-10-10','2026-09-18','2026-10-16']
    for market in MARKETS:
        valid=f[f.market_id.eq(market)&f.measurement_valid]
        for desired in requested:
            point=valid.iloc[(valid.asof_date-pd.Timestamp(desired)).abs().argsort().iloc[0]]
            actual=direct_window(market,point.asof_date)
            for col in CORE+['worst_cumulative_return','correlation_stocks','correlation_union_stocks','min_members','min_return_stocks']:
                np.testing.assert_allclose(actual[col],point[col],rtol=2e-10,atol=1e-14,err_msg=f'{market} {point.asof_date} {col}')
            rows.append(dict(market_id=market,asof_date=point.asof_date,direction='future',window_length=20,**actual))
        for h,date in [(20,'2025-10-10'),(5,'2026-10-16'),(60,'2026-10-16')]:
            point=past[past.market_id.eq(market)&past.window_length.eq(h)&past.asof_date.eq(date)].iloc[0]
            actual=direct_window(market,date,h,'past')
            for col in CORE+['worst_cumulative_return']:np.testing.assert_allclose(actual[col],point[col],rtol=2e-10,atol=1e-14)
            rows.append(dict(market_id=market,asof_date=pd.Timestamp(date),direction='past',window_length=h,**actual))
        print('independent arithmetic',market,flush=True)
    frame('release/independent_replays',pd.DataFrame(rows));return len(rows)

def continuity_audit():
    c=db()
    stats=c.execute("""WITH parents AS(SELECT *,lag(close*adj_factor) OVER w prev_adjusted,
        lag(pos) OVER w prev_pos,lag(volume_shares) OVER w prev_volume FROM read_parquet(?)
        WINDOW w AS(PARTITION BY instrument_id ORDER BY date)),replay AS(
        SELECT *,CASE WHEN pos-prev_pos=1 AND volume_shares>0 AND prev_volume>0 THEN ln(close*adj_factor/prev_adjusted) END direct_r FROM parents)
        SELECT count(*) observation_rows,count(r) valid_returns,max(abs(r-direct_r)) max_difference,
        count(*) FILTER(WHERE (r IS NULL)!=(direct_r IS NULL)) validity_disagreements FROM replay""",[str(OUT/'cache/stocks/*.parquet')]).df().iloc[0].to_dict()
    assert stats['max_difference']<1e-11 and stats['validity_disagreements']==0,stats
    # Verify source units before and after the provider handoff, and for BJ.
    units=[]
    for date in ['20140103','20150706','20200102','20250506','20251009','20260922','20260923','20261113']:
        year=date[:4];tail=OUT/'sources/daily'/(date+'.parquet')
        if tail.exists():d=pd.read_parquet(tail);d['volume_shares']=d.vol*100;d['amount_cny']=d.amount*1000
        else:d=c.execute("SELECT ts_code,vol,amount,volume_shares,amount_cny FROM read_parquet(?) WHERE trade_date=?",[str(BASE/f'stock_daily_observations/{year}.parquet'),date]).df()
        assert np.allclose(d.vol*100,d.volume_shares,equal_nan=True)
        assert np.allclose(d.amount*1000,d.amount_cny,equal_nan=True)
        units.append(dict(date=date,rows=len(d),volume_factor=100,amount_factor=1000))
    q=c.execute('SELECT instrument_id,ts_code,date,r FROM read_parquet(?) WHERE abs(r)>.65',[str(OUT/'cache/stocks/*.parquet')]).df();c.close()
    ids=read('security_history').groupby('instrument_id').valid_from.min();cal=pd.DatetimeIndex(read('calendar').date)
    q['listing_date']=q.instrument_id.map(ids)
    q['trading_days_since_listing']=[int(((cal>=start)&(cal<=end)).sum()) for start,end in zip(q.listing_date,q.date)]
    q['decision']=np.where(q.trading_days_since_listing.le(5),'IPO_INITIAL_FIVE_TRADING_DAYS_NO_DAILY_LIMIT','REQUIRES_REVIEW')
    assert not q.decision.eq('REQUIRES_REVIEW').any(),q[q.decision.eq('REQUIRES_REVIEW')]
    frame('release/large_return_adjudications',q);frame('release/unit_checks',pd.DataFrame(units))
    write(REPORT/'continuity_validation.json',stats);return stats

def full_constraints():
    f=read('future_window_outcomes');p=read('past_window_outcomes');prices=read('index_prices').set_index(['ts_code','date']).close
    cal=pd.DatetimeIndex(read('calendar').date)
    for direction,frame_ in [('future',f),('past',p)]:
        for r in frame_[frame_.measurement_valid].rename(columns={'return':'R'}).itertuples():
            i=cal.get_loc(r.asof_date);h=r.window_length;a,b=(i,i+h) if direction=='future' else (i-h,i)
            path=prices.loc[r.market_id].reindex(cal[a:b+1]).to_numpy();log=np.log(path[1:]/path[:-1])
            assert len(path)==h+1 and b-a==h
            expected=[path[-1]/path[0]-1,np.sqrt(252*np.mean(log*log)),max(1-path[j]/max(path[:j+1]) for j in range(h+1)),min(path[1:]/path[0]-1)]
            np.testing.assert_allclose([r.R,r.volatility,r.drawdown,r.worst_cumulative_return],expected,rtol=1e-10,atol=1e-14)
            assert 0<=r.drawdown<=1 and r.volatility>=0 and r.amihud>=0 and r.turnover>=0
            assert 0<=r.breadth<=1 and -1-1e-12<=r.correlation<=1+1e-12
            assert 2<=r.correlation_stocks<=r.correlation_union_stocks
            for value in [r.quote_coverage,r.float_coverage,r.return_coverage,r.correlation_coverage,r.suspension_fraction]:assert 0<=value<=1
    return dict(future_windows=int(f.measurement_valid.sum()),past_windows=int(p.measurement_valid.sum()))

def causal_replay():
    from .measure import build_measures
    from .dictionary import training_rows
    boundary=pd.Timestamp('2019-12-31');expected=read('past_window_outcomes');expected=expected[expected.asof_date.le(boundary)].reset_index(drop=True)
    def perturb(d):
        mask=d.date.gt(boundary)
        for col in ['r','volume_shares','amount_cny','float_shares','close']:d.loc[mask,col]=123.456
        return d
    def perturb_prices(d):d.loc[d.date.gt(boundary),'close']*=10;return d
    altered=build_measures(max_asof=boundary,stock_transform=perturb,price_transform=perturb_prices,save=False)
    pd.testing.assert_frame_equal(expected,altered['past_window_outcomes'].reset_index(drop=True),check_dtype=False,check_exact=True)
    original_train=training_rows(read('future_window_outcomes'));new_train=training_rows(altered['future_window_outcomes'])
    pd.testing.assert_frame_equal(original_train.reset_index(drop=True),new_train.reset_index(drop=True),check_dtype=False,check_exact=True)
    truncated=build_measures(max_asof=boundary,stock_transform=lambda d:d[d.date.le(boundary)],
        price_transform=lambda d:d.assign(close=d.close.where(d.date.le(boundary))),save=False)
    pd.testing.assert_frame_equal(expected,truncated['past_window_outcomes'].reset_index(drop=True),check_dtype=False,check_exact=True)
    from .formal import macro_facts
    from .macro import align,prepare
    facts=macro_facts();points=read('future_window_outcomes')[['asof_date','asof_time']].drop_duplicates().sort_values('asof_date')
    points=points[points.asof_date.le(boundary)]
    original_macro=align(facts,points)[0]
    legal=prepare(facts);past_ids=set(legal.loc[legal.effective_available_at.le(clock(boundary)),'source_record_id'])
    future=facts.copy();future.loc[~future.source_record_id.isin(past_ids),'value']=999.
    pd.testing.assert_frame_equal(original_macro,align(future,points)[0])
    pd.testing.assert_frame_equal(original_macro,align(facts[facts.source_record_id.isin(past_ids)],points)[0])
    write(REPORT/'causal_replay.json',dict(boundary=str(boundary.date()),intermediate_stock_and_index_prices_mutated=True,
        historical_truncation=True,past_windows_compared=len(expected),training_dictionary_rows_compared=len(original_train),passed=True))
    return len(expected)

def verify_acceptance(causal=True):
    results=dict(independent_replays=independent_replays(),full_constraints=full_constraints(),continuity=continuity_audit())
    if causal:results['causal_windows_compared']=causal_replay()
    spec=json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    write(REPORT/'acceptance_validation.json',dict(passed=True,results=results,supervised_models_run=0,
        target_version=spec['target_version'],feature_version=spec['feature_version'],
        calculation_code_hash=code_hash()));return results
