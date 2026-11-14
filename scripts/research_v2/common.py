"""Offline, read-only source boundary and frozen research protocol."""
from __future__ import annotations
import hashlib
import json
import os
import platform
import shutil
import time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import pyarrow

BASE = Path(r'E:\MLEC')
SOURCE = Path(r'E:\QuantData')
CONFIG = BASE/'config/research_v2'
DATA = BASE/'data/research_v2'
AUDIT = BASE/'audit/research_v2'
REPORT = BASE/'reports/research_v2'
TZ = 'Asia/Shanghai'
PROTOCOL = {
    'protocol_version':'market-research-v2.0.0', 'timezone':TZ,
    'index_code':'000300.SH', 'price_basis':'price_index_no_dividend',
    'start':'2015-01-05','end':'2026-09-22', 'asof_hour':18,
    'historical_windows':[5,20,60], 'state_window':20,
    'horizons':[20,5,40], 'reference_start':'2015-01-01',
    'reference_end':'2019-12-31','development_years':[2020,2021,2022],
    'heldout_start':'2023-01-01', 'quantile':0.80,
    'quantile_method':'numpy.quantile(method=linear)',
    'exit_normal_days':5, 'loss_metric':'mdd_20d',
    'single_factor_sensitivity':[
        {'id':'q75','quantile':0.75}, {'id':'q85','quantile':0.85},
        {'id':'exit3','exit_normal_days':3}, {'id':'exit10','exit_normal_days':10},
        {'id':'terminal_drawdown','loss_metric':'current_drawdown_20d'},
        {'id':'h5','horizon':5}, {'id':'h40','horizon':40}],
    'annualization':252,'basic_lag_trading_days':1,
    'basic_availability':'observation on d-1 assumed available at d 18:00; actual provider intraday time UNKNOWN',
    'market_availability':'historical provider reconstruction assumed known at d 18:00, not independently observed historical publication time',
    'initialization':'require exit_normal_days consecutive known normal days; first observed stress before confirmation is left_censored',
    'unknown_gap':'break episode knowledge; mark interrupted episode right_censored; reinitialize after gap',
    'label_release':'full horizon endpoint at 18:00 for both positive and negative labels',
    'weekly_rule':'last actual SSE open day of complete ISO calendar week',
    'future_worst_return':'minimum(P_j/P_t-1) for j=t+1..t+H',
    'stock_scope':'observed SH/SZ A-share codes, including delisted; no current-list-status screening',
    'stock_return':'simple adjusted return close_t/close_prev * factor_t/factor_prev - 1, only consecutive SSE dates',
    'stock_liquidity':'abs(simple_adjusted_return)/amount_cny; 20 valid consecutive daily values per stock; equal-weight mean and median',
    'stock_exclusions':'non-SH/SZ A-share; absent master; outside reconstructed listing span; S suspension on either endpoint; nonpositive price/factor/amount; nonadjacent dates',
    'stock_correlation':'60 complete consecutive daily adjusted simple returns; positive sample std; identical dates for all columns, no pairwise deletion; equal-pair average via standardized-column sum identity',
    'stock_optional_features_required_for_primary':False,
    'proxy_quantile':0.80,'activity_low_quantile':0.20,
    'final_update':'monthly before first weekly prediction, fit_cutoff previous SSE open day 18:00; mature historical labels only',
    'budget_bytes':2*1024**3,'minimum_free_bytes':5*1024**3,
    'duckdb_memory':'1GB','duckdb_threads':1,
    'no_training':True,'no_macro_effectiveness_claim':True,
}

def canonical(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()
def objhash(obj): return hashlib.sha256(canonical(obj)).hexdigest()
def filehash(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(4*1024**2),b''): h.update(b)
    return h.hexdigest()
def jsonwrite(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.partial')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    os.replace(tmp,path)
def readjson(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def stamp(d):
    s=pd.Series(pd.to_datetime(d))
    return s.dt.tz_localize(TZ)+pd.Timedelta(hours=18)
def budget():
    paths=[CONFIG,DATA,AUDIT,REPORT,BASE/'scripts/research_v2',BASE/'tests/research_v2']
    used=sum(p.stat().st_size for root in paths for p in root.rglob('*') if p.is_file())
    free=shutil.disk_usage(BASE).free
    if used>PROTOCOL['budget_bytes'] or free<PROTOCOL['minimum_free_bytes']:
        raise RuntimeError(f'Budget gate: new artifacts {used} bytes, disk free {free} bytes')
    return {'artifact_bytes':used,'free_bytes':free}
def saveframe(path,frame):
    budget();path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.parquet.partial');frame.to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,path);budget()
def log(stage,**kwargs):
    row={'time':pd.Timestamp.now(tz=TZ).isoformat(),'stage':stage,**kwargs}
    with (AUDIT/'logs/pipeline.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
    print(stage,json.dumps(kwargs,ensure_ascii=False,default=str),flush=True)
def db():
    c=duckdb.connect();c.execute('SET threads=1');c.execute("SET memory_limit='1GB'")
    c.execute("SET temp_directory='E:/MLEC/audit/research_v2/temp'")
    c.execute('SET preserve_insertion_order=false');return c
def qs(s):return "'"+str(s).replace("'","''")+"'"
def source(ep):
    rows=readjson(AUDIT/'source_manifest.json')['datasets'][ep]
    return 'read_parquet(['+','.join(qs(r['path']) for r in rows)+'],union_by_name=true,hive_partitioning=false)'
def latest(ep,where='true'):
    # Exactly the registered revision/content resolution, filtered on stable symbol/date keys.
    keys={'trade_cal':'exchange,cal_date','stock_basic':'ts_code','bse_mapping':'_row_hash','suspend_d':'_row_hash','namechange':'_row_hash'}.get(ep,'ts_code,trade_date')
    return f'SELECT * FROM (SELECT * FROM {source(ep)} WHERE {where} QUALIFY row_number() OVER(PARTITION BY _row_hash,_ingested_at ORDER BY _batch_id)=1) QUALIFY row_number() OVER(PARTITION BY {keys} ORDER BY _ingested_at DESC,_row_hash DESC)=1'
def query(c,sql,tag):
    start=time.perf_counter();result=c.execute(sql).df()
    with (AUDIT/'queries.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'tag':tag,'sql':sql,'rows':len(result),'seconds':time.perf_counter()-start})+'\n')
    budget();return result
def freeze():
    cfg={**PROTOCOL,'implementation':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'pyarrow':pyarrow.__version__,'duckdb':duckdb.__version__}}
    path=CONFIG/'research_config.json'
    if path.exists() and readjson(path)!=cfg:raise RuntimeError('Frozen config changed; use a new protocol namespace/version')
    if not path.exists():jsonwrite(path,cfg)
    jsonwrite(CONFIG/'protocol_hash.json',{'sha256':objhash(cfg),'frozen_before_computation':True,'initial_config_file_mtime_ns':path.stat().st_mtime_ns})
    # Only selected registered dependencies, no recursive source scan.
    endpoints=['index_daily','index_dailybasic','trade_cal','daily','adj_factor','stock_basic','suspend_d','bse_mapping','namechange']
    reg=duckdb.connect(str(SOURCE/'quant.duckdb'),read_only=True)
    datasets={};manifest_path=AUDIT/'source_manifest.json'
    previous=readjson(manifest_path) if manifest_path.exists() else None
    for ep in endpoints:
        rows=reg.execute('SELECT path,rows,content_hash FROM canonical_parts WHERE active AND endpoint=? ORDER BY path',[ep]).fetchall()
        if not rows:raise RuntimeError(f'Missing active dependency {ep}')
        records=[]
        for path,n,expected in rows:
            p=Path(path);st=p.stat()
            old=next((r for r in previous['datasets'][ep] if r['path']==path),None) if previous else None
            if old and old['bytes']==st.st_size and old['mtime_ns']==st.st_mtime_ns and old['registered_hash']==expected:
                actual=old['verified_hash']
            else:actual=filehash(p)
            if actual!=expected:raise RuntimeError('Source hash mismatch: '+path)
            records.append({'path':path,'registered_rows':n,'registered_hash':expected,'verified_hash':actual,'bytes':st.st_size,'mtime_ns':st.st_mtime_ns})
        datasets[ep]=records;log('source_verified',dataset=ep,files=len(records))
    views=reg.execute("SELECT view_name,sql FROM duckdb_views() WHERE view_name IN ('canonical_index_daily','canonical_index_dailybasic','canonical_trade_cal')").fetchall()
    reg.close();st=(SOURCE/'quant.duckdb').stat()
    snap={'datasets':datasets,'database_stat':{'bytes':st.st_size,'mtime_ns':st.st_mtime_ns},'logical_policy':'revision(_row_hash,_ingested_at), latest natural key by _ingested_at DESC,_row_hash DESC','source_view_sql':views}
    if previous and objhash(previous)!=objhash(snap):raise RuntimeError('Frozen sources changed; no silent replacement')
    jsonwrite(manifest_path,snap);jsonwrite(AUDIT/'source_version.json',{'source_version':objhash(snap),'protocol_hash':objhash(cfg)})
    jsonwrite(AUDIT/'environment.json',cfg['implementation'])
    return cfg

def read_index():
    c=db();cal=query(c,f"SELECT exchange,cal_date,is_open,pretrade_date FROM ({latest('trade_cal')}) WHERE exchange='SSE' ORDER BY cal_date",'SSE_calendar')
    cal['date']=pd.to_datetime(cal.cal_date,format='%Y%m%d');cal['is_open']=cal.is_open.astype(int)
    assert cal.date.is_unique
    assert cal.date.diff().dropna().eq(pd.Timedelta(days=1)).all()
    calendar=cal.loc[cal.is_open.eq(1),'date'].reset_index(drop=True)
    predicate="ts_code='000300.SH'"
    idx=query(c,f"SELECT * FROM ({latest('index_daily', predicate)}) ORDER BY trade_date",'CSI300_daily')
    basic=query(c,f"SELECT * FROM ({latest('index_dailybasic', predicate)}) ORDER BY trade_date",'CSI300_dailybasic')
    c.close()
    idx['date']=pd.to_datetime(idx.trade_date,format='%Y%m%d');basic['date']=pd.to_datetime(basic.trade_date,format='%Y%m%d')
    expected=calendar.between(PROTOCOL['start'],PROTOCOL['end'])
    assert idx.date.is_unique and idx.date.tolist()==calendar[expected].tolist(),'Hard error: price/calendar disagreement'
    assert idx.date.tolist()==basic.date.tolist(),'Hard error: dailybasic coverage differs'
    assert np.isfinite(idx[['open','high','low','close','vol','amount']].to_numpy()).all()
    assert (idx[['open','high','low','close']]>0).all().all()
    assert idx.low.le(idx[['open','close']].min(axis=1)).all() and idx.high.ge(idx[['open','close']].max(axis=1)).all()
    assert (idx[['vol','amount']]>=0).all().all()
    # Retain provenance, never reinterpret collection timestamps as historical publication times.
    keep=['date','ts_code','open','high','low','close','pre_close','change','pct_chg','vol','amount','_row_hash','_batch_id','_ingested_at','_available_at']
    clean=idx[keep].rename(columns={'ts_code':'index_code','_available_at':'source_available_at','_ingested_at':'source_ingested_at','_row_hash':'source_row_hash','_batch_id':'source_batch_id'})
    clean['amount_cny']=clean.amount*1000
    clean['research_available_at']=stamp(clean.date)
    clean['availability_basis']=PROTOCOL['market_availability']
    fields=[x for x in basic if not x.startswith('_') and x not in ['date','ts_code','trade_date']]
    for field in fields:clean['basic_raw_'+field]=basic[field].to_numpy()
    clean['basic_source_available_at']=basic['_available_at'].to_numpy()
    clean['basic_source_row_hash']=basic['_row_hash'].to_numpy()
    clean['basic_observation_date']=clean.date.shift(1)
    clean['basic_research_available_at']=clean.research_available_at.where(clean.basic_observation_date.notna())
    clean['basic_availability_basis']=PROTOCOL['basic_availability']
    clean['protocol_version']=PROTOCOL['protocol_version']
    saveframe(DATA/'market_daily_clean.parquet',clean);saveframe(AUDIT/'sse_calendar.parquet',cal)
    diff=pd.DataFrame({'date':clean.date,'pre_close_minus_prior_close':clean.pre_close-clean.close.shift(1),'source_pct_minus_simple_pct':clean.pct_chg-100*(clean.close/clean.close.shift(1)-1)})
    saveframe(AUDIT/'return_consistency.parquet',diff)
    jsonwrite(AUDIT/'dependency_checks.json',{'price_rows':len(clean),'price_start':str(clean.date.min().date()),'price_end':str(clean.date.max().date()),'dailybasic_rows':len(basic),'max_pre_close_difference':diff.pre_close_minus_prior_close.abs().max(),'max_source_pct_difference_percentage_points':diff.source_pct_minus_simple_pct.abs().max(),'prior_audit_rows_match':len(clean)==2850,'design_documents_found':False})
    return clean,cal
