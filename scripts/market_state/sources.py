"""Read-only lake projections and preserved, repaired local data."""
import numpy as np
import pandas as pd
from .common import *

def parq(c, path, cols='*'):
    return c.execute(f'SELECT {cols} FROM read_parquet(?,union_by_name=true)', [str(path)]).df()

def load_suspensions(master):
    parts=[]
    for p in (BASE/'stock_trading_status').glob('*.parquet'):
        f=pd.read_parquet(p,columns=['instrument_id','trade_date','status'])
        f=f[f.status.isin(['SUSPENDED_OFFICIAL_EVIDENCE','SUSPENDED_SOURCE_RECORDED'])].copy()
        f['evidence_path']=p.relative_to(ROOT).as_posix();parts.append(f)
    alias=master[['ts_code','instrument_id']].drop_duplicates()
    paths=list((OUT/'sources/suspend_d').glob('*.parquet'))+[OUT/'cache/bse_suspensions.parquet']+list((OUT/'sources/bse_repair/suspend_d').glob('*.parquet'))
    for p in paths:
        if not p.exists():continue
        f=pd.read_parquet(p);f=f[f.suspend_type.eq('S')].merge(alias,on='ts_code')
        f['status']='SUSPENDED_SOURCE_RECORDED';f['evidence_path']=p.relative_to(ROOT).as_posix()
        parts.append(f[['instrument_id','trade_date','status','evidence_path']])
    result=pd.concat(parts,ignore_index=True).drop_duplicates(['instrument_id','trade_date'])
    result['date']=pd.to_datetime(result.trade_date)
    return result

def identities(c):
    master = pd.read_parquet(BASE/'stock_master_history.parquet')
    cols=['instrument_id','ts_code','valid_from','valid_to','security_type','identity_evidence']
    master=master[cols].copy()
    fresh=pd.concat([pd.read_parquet(p) for p in (OUT/'sources').glob('stock_basic_*.parquet')],ignore_index=True)
    for r in fresh[fresh.delist_date.notna()].itertuples():
        # Newly reported delistings shorten open-ended prior histories; old
        # identity/code transitions remain intact.
        mask=master.ts_code.eq(r.ts_code)
        end=pd.to_datetime(r.delist_date)
        master.loc[mask&master.valid_to.gt(end),'valid_to']=end
    # Retain historical code intervals, rather than replacing them by today's master.
    rows=[]
    for r in fresh.itertuples():
        if r.ts_code in set(master.ts_code) or r.exchange=='BSE':continue
        if not ((r.ts_code.endswith('.SH') and r.ts_code.startswith('6') and not r.ts_code.startswith('689')) or
                (r.ts_code.endswith('.SZ') and r.ts_code[0] in '03')):continue
        rows.append(dict(instrument_id='CN-EQUITY-'+r.ts_code,ts_code=r.ts_code,
            valid_from=pd.to_datetime(r.list_date),valid_to=pd.to_datetime(r.delist_date) if pd.notna(r.delist_date) else pd.Timestamp('2099-12-31'),
            security_type='A_SHARE',identity_evidence='Tushare stock_basic current listing/delisting reconstruction'))
    mapping=c.execute('SELECT DISTINCT o_code,n_code,list_date,name FROM lake.canonical_bse_mapping').df()
    # Six officially announced pilots switched before the remaining stock.
    pilot_names=['颖泰生物','艾融软件','龙竹科技','佳先股份','同享科技','球冠电缆']
    bse=fresh[fresh.exchange.eq('BSE')].copy(); changes=[]
    for r in bse.itertuples():
        m=mapping[mapping.n_code.eq(r.ts_code)]
        start=max(pd.to_datetime(r.list_date),pd.Timestamp('2021-11-15'))
        end=pd.to_datetime(r.delist_date) if pd.notna(r.delist_date) else pd.Timestamp('2099-12-31')
        identity='CN-EQUITY-'+r.ts_code
        if len(m):
            m=m.iloc[0];switch=pd.Timestamp('2025-05-06' if m['name'] in pilot_names else '2025-10-09')
            rows.append(dict(instrument_id=identity,ts_code=m.o_code,valid_from=start,valid_to=min(end,switch),security_type='A_SHARE',identity_evidence='bse_mapping; BSE code-switch notice'))
            changes.append(dict(instrument_id=identity,old_code=m.o_code,new_code=r.ts_code,effective_date=switch))
            start=max(start,switch)
        rows.append(dict(instrument_id=identity,ts_code=r.ts_code,valid_from=start,valid_to=end,security_type='A_SHARE',identity_evidence='BSE mapping + stock_basic; listing before BSE opening clamped to opening'))
    master=pd.concat([master,pd.DataFrame(rows)],ignore_index=True)
    master=master[master.security_type.eq('A_SHARE') & master.valid_from.lt(master.valid_to)]
    frame('security_history',master);frame('bse_code_changes',pd.DataFrame(changes))
    return master

def build_sources(force=False):
    c=db();c.execute("ATTACH 'E:/QuantData/quant.duckdb' AS lake (READ_ONLY)")
    master=identities(c)
    indices=pd.concat([pd.read_parquet(p) for p in (OUT/'sources').glob('index_*.parquet')],ignore_index=True)
    indices['date']=pd.to_datetime(indices.trade_date)
    frame('index_prices',indices)
    calendar=pd.read_parquet(OUT/'sources/trade_calendar.parquet')
    observed=indices.date
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.exchange.eq('SSE')&calendar.is_open.astype(str).eq('1'),'cal_date']))
    dates=dates[(dates>=observed.min())&(dates<=observed.max())].sort_values().unique()
    frame('calendar',pd.DataFrame({'date':dates}))
    weights=parq(c,BASE/'index_weights_history/*.parquet','index_code,con_code,trade_date,weight')
    extra=[pd.read_parquet(p) for p in (OUT/'sources').glob('weights_*.parquet')]
    weights=pd.concat([weights]+extra,ignore_index=True)
    weights=weights[weights.index_code.isin(list(MARKETS)[1:])].drop_duplicates(['index_code','con_code','trade_date'],keep='last')
    weights['snapshot_date']=pd.to_datetime(weights.trade_date)
    weights['precision']='observed_snapshot_carried_forward_max_45_calendar_days; not exact daily membership or weights'
    frame('membership_snapshots',weights[['index_code','con_code','snapshot_date','weight','precision']])
    # Compact BJ-only projection: no whole-lake copy. Metadata remains in the lake.
    bjpath=OUT/'cache/bse.parquet';bjpath.parent.mkdir(parents=True,exist_ok=True)
    if force or not bjpath.exists():
        bj=c.execute("""SELECT d.ts_code,d.trade_date,d.close,d.vol*100 volume_shares,d.amount*1000 amount_cny,
          b.float_share*10000 float_shares,a.adj_factor
          FROM lake.canonical_daily d LEFT JOIN lake.canonical_daily_basic b USING(ts_code,trade_date)
          LEFT JOIN lake.canonical_adj_factor a USING(ts_code,trade_date)
          WHERE d.ts_code LIKE '%.BJ' AND d.trade_date>='20211112'""").df()
        bj.to_parquet(bjpath,index=False,compression='zstd')
    bj=pd.read_parquet(bjpath)
    suspension_path=OUT/'cache/bse_suspensions.parquet'
    if force or not suspension_path.exists():
        c.execute("SELECT ts_code,trade_date,suspend_type FROM lake.canonical_suspend_d WHERE ts_code LIKE '%.BJ'").df().to_parquet(suspension_path,index=False)
    aliases=master[['instrument_id','ts_code']].drop_duplicates()
    c.register('aliases',aliases)
    c.register('identity',master)
    c.register('calendar',pd.DataFrame({'trade_date':dates.strftime('%Y%m%d'),'pos':range(len(dates))}))
    blocked=c.execute("SELECT instrument_id,trade_date FROM read_parquet(?) WHERE field='float_share' AND quality_status LIKE 'BLOCKED%'",[str(BASE/'market_data_quality.parquet')]).df()
    c.register('blocked_float',blocked[['instrument_id','trade_date']].drop_duplicates())
    coverage=[]
    for year in sorted(set(dates.year)):
        path=OUT/f'cache/stocks/{year}.parquet';path.parent.mkdir(parents=True,exist_ok=True)
        parents=[BASE/f'{n}/{year}.parquet' for n in ['stock_daily_observations','stock_daily_basic_observations','stock_adjustment_observations']]
        parents += [p for n in ['daily','daily_basic','adj_factor'] for p in (OUT/'sources'/n).glob(f'{year}*.parquet')]
        stamp=digest(dict(parents=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in parents if p.exists()],
            identity=master.to_dict('records'),bse=(bjpath.stat().st_size,bjpath.stat().st_mtime_ns),calendar_end=str(dates.max()),normalization='adjacent-adjusted-close-v1'))
        meta=path.with_suffix('.json')
        if path.exists() and meta.exists() and json.loads(meta.read_text())['fingerprint']==stamp and not force:
            q=pd.read_parquet(path,columns=['date','instrument_id','r']);coverage.append(dict(year=year,rows=len(q),returns=int(q.r.notna().sum())));continue
        local=BASE/f'stock_daily_observations/{year}.parquet'
        parts=[]
        if local.exists():
            q=c.execute("""SELECT d.instrument_id,d.ts_code,d.trade_date,d.close,d.volume_shares,d.amount_cny,
               b.float_share*10000 float_shares,a.adj_factor
               FROM read_parquet(?) d LEFT JOIN read_parquet(?) b USING(instrument_id,trade_date)
               LEFT JOIN read_parquet(?) a USING(instrument_id,trade_date)""",
               [str(local),str(BASE/f'stock_daily_basic_observations/{year}.parquet'),str(BASE/f'stock_adjustment_observations/{year}.parquet')]).df()
            parts.append(q.drop(columns='instrument_id'))
        parts.append(bj[bj.trade_date.str.startswith(str(year))])
        for p in (OUT/'sources/daily').glob(f'{year}*.parquet'):
            d=pd.read_parquet(p);b=pd.read_parquet(OUT/'sources/daily_basic'/p.name);a=pd.read_parquet(OUT/'sources/adj_factor'/p.name)
            q=d[['ts_code','trade_date','close','vol','amount']].merge(b[['ts_code','trade_date','float_share']],on=['ts_code','trade_date'],how='left').merge(a[['ts_code','trade_date','adj_factor']],on=['ts_code','trade_date'],how='left')
            q['volume_shares']=q.vol*100;q['amount_cny']=q.amount*1000;q['float_shares']=q.float_share*10000
            parts.append(q.drop(columns=['vol','amount','float_share']))
        raw=pd.concat(parts,ignore_index=True).drop_duplicates(['ts_code','trade_date'],keep='last')
        c.register('raw',raw)
        q=c.execute("""SELECT a.instrument_id,h.ts_code,r.* EXCLUDE(ts_code),cal.pos
          FROM raw r JOIN aliases a USING(ts_code) JOIN calendar cal USING(trade_date)
          JOIN identity h ON a.instrument_id=h.instrument_id
          AND strptime(r.trade_date,'%Y%m%d')>=h.valid_from AND strptime(r.trade_date,'%Y%m%d')<h.valid_to
          QUALIFY row_number() OVER(PARTITION BY a.instrument_id,r.trade_date ORDER BY (r.ts_code=h.ts_code) DESC,r.ts_code)=1""").df()
        q['date']=pd.to_datetime(q.trade_date);q['adj_close']=q.close*q.adj_factor
        bad=set(blocked.loc[blocked.trade_date.str.startswith(str(year)),['instrument_id','trade_date']].itertuples(index=False,name=None))
        if bad:q.loc[[tuple(k) in bad for k in q[['instrument_id','trade_date']].itertuples(index=False,name=None)],'float_shares']=np.nan
        prior=OUT/f'cache/stocks/{year-1}.parquet'
        if prior.exists():
            prev=pd.read_parquet(prior,columns=['instrument_id','date','pos','adj_close','volume_shares']).sort_values('date').groupby('instrument_id').tail(1)
            combined=pd.concat([prev,q],ignore_index=True).sort_values(['instrument_id','date'])
        else:combined=q.sort_values(['instrument_id','date']).copy()
        g=combined.groupby('instrument_id');r=np.log(combined.adj_close/g.adj_close.shift())
        r=r.where(g.pos.diff().eq(1)&combined.volume_shares.gt(0)&g.volume_shares.shift().gt(0))
        combined['r']=r; q=combined[combined.date.dt.year.eq(year)].copy()
        q.to_parquet(path,index=False,compression='zstd')
        write(meta,dict(fingerprint=stamp,source_paths=[str(p) for p in parents if p.exists()],rows=len(q),version=VERSION))
        coverage.append(dict(year=year,rows=len(q),returns=int(q.r.notna().sum())))
        print('normalized',year,len(q),flush=True)
    frame('source_coverage',pd.DataFrame(coverage));c.close()
    write(OUT/'market_universe.json',dict(version=VERSION,markets=MARKETS,
        overall_price='000985.SH = provider 000985.CSI',overall_cross_section='historical listed SSE/SZSE A shares + BSE from 2021-11-15; CDR excluded',
        identity='security_history.parquet; valid_from inclusive / valid_to exclusive',
        membership='membership_snapshots.parquet; last observed snapshot, maximum age 45 days; no current constituent backfill',
        units=dict(amount='CNY',volume='shares',float_shares='shares',turnover='ratio',return_type='log adjusted stock close, adjacent exchange dates; no zero filling'),
        sources=['E:/QuantData/quant.duckdb READ_ONLY','preserved repaired standardized market/v4','sources/*.parquet targeted Tushare supplements'],
        bse_evidence=['https://www.bse.cn/important_news/200025487.html','https://www.beijing.gov.cn/ywdt/gzdt/202510/t20251010_4218545.html'],
        strict_original_vintage=False))
