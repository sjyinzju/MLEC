"""Baseline, external catalogue and bounded raw extraction; no external writes."""
import ast
import subprocess
import pyarrow.parquet as pq
from .common import *

REQUIRED = {'index_daily','index_dailybasic','index_basic','daily','daily_basic','adj_factor','stock_basic','namechange','suspend_d','trade_cal','index_weight'}
CANDIDATE = {'margin','margin_detail','margin_secs','moneyflow','stk_limit','daily_info','sz_daily_info','hsgt_top10','index_member_all','index_classify','bse_mapping','new_share','dividend','shibor','shibor_lpr','shibor_quote','cn_cpi','cn_gdp','cn_m','cn_pmi','cn_ppi','cn_schedule','sf_month','gz_index','wz_index','block_trade','top_list','top_inst'}
EXTRACT = REQUIRED | (CANDIDATE-{'index_member_all','index_classify','cn_cpi','cn_gdp','cn_m','cn_pmi','cn_ppi','cn_schedule','sf_month','gz_index','wz_index','block_trade','top_list','top_inst','margin_secs'})

def baseline():
    target=AUDIT/'integrity/baseline.json'
    if target.exists():return read(target)
    excluded={'.git','.local_deps','.pytest_cache','__pycache__'}
    files={}
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or any(x in excluded for x in p.relative_to(ROOT).parts) or p.is_relative_to(AUDIT) or 'final_data_foundation' in p.parts:continue
        files[p.relative_to(ROOT).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size}
    result={'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'git_status':subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True),
            'files':files,'created_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'free_bytes':budget()}
    write(target,result)
    return result

def external():
    target=AUDIT/'integrity/external_manifest.json'
    if target.exists():return read(target)
    with duckdb.connect(str(SOURCE/'quant.duckdb'),read_only=True) as c:
        parts=c.execute('SELECT endpoint,path,rows,content_hash FROM canonical_parts WHERE active ORDER BY endpoint,path').df().to_dict('records')
        tasks=c.execute('SELECT endpoint,status,error_kind,count(*) tasks,sum(rows) row_count FROM fetch_tasks GROUP BY ALL ORDER BY 1,2,3').df()
        frame(AUDIT/'source_reconciliation/external_fetch_status.parquet',tasks)
        schemas={}
        for ep in sorted({p['endpoint'] for p in parts}):
            schemas[ep]=[{'field':r[0],'type':r[1]} for r in c.execute('DESCRIBE canonical_'+ep).fetchall()]
    for p in parts:
        st=Path(p['path']).stat();p.update(bytes=st.st_size,mtime_ns=st.st_mtime_ns)
        if p['endpoint'] in EXTRACT:
            p['verified_sha256']=sha(p['path'])
            if p['verified_sha256']!=p['content_hash']:raise ValueError('External registered hash mismatch '+p['path'])
    st=(SOURCE/'quant.duckdb').stat()
    obj={'database':{'path':str(SOURCE/'quant.duckdb'),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':sha(SOURCE/'quant.duckdb')},'parts':parts,'schemas':schemas}
    write(target,obj)
    rows=[]
    for ep in schemas:
        ps=[p for p in parts if p['endpoint']==ep]
        status='REQUIRED' if ep in REQUIRED else 'CANDIDATE' if ep in CANDIDATE else 'OUT_OF_SCOPE'
        reason='Market identity, coverage, adjustment, index structure or mandatory market measurements' if status=='REQUIRED' else 'Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability' if status=='CANDIDATE' else 'Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set'
        rows.append({'source_dataset':ep,'scope':status,'reason':reason,'active_parts':len(ps),'registered_rows':sum(p['rows'] for p in ps),'bytes':sum(p['bytes'] for p in ps),'fields':json.dumps(schemas[ep],ensure_ascii=False)})
    frame(AUDIT/'market_coverage/external_catalogue.parquet',pd.DataFrame(rows))
    # Registered parts define dataset inventory. Do not walk 1.6 million inactive
    # snapshots merely to rediscover the registry; selected active parts are hashed.
    frame(AUDIT/'integrity/external_active_files.parquet',pd.DataFrame(parts))
    return obj

def extract(endpoints=None):
    obj=external();c=db();ledger_path=AUDIT/'integrity/raw_extraction.json'
    ledger=read(ledger_path) if ledger_path.exists() else {}
    for ep in sorted(endpoints or EXTRACT):
        fields={x['field'] for x in obj['schemas'][ep]}
        predicate='true'
        if ep in {'daily','daily_basic','adj_factor','stock_basic','namechange','suspend_d','moneyflow','stk_limit','margin_detail'}:predicate=A_SCOPE
        if ep in {'index_daily','index_dailybasic','index_basic'}:predicate='ts_code IN ('+','.join(qs(s) for s in INDEX_CODES)+')'
        if ep=='index_weight':predicate='index_code IN ('+','.join(qs(s) for s in INDEX_CODES)+')'
        for year in (range(2014,2027) if 'trade_date' in fields else [None]):
            pred=predicate
            if year:pred+=f" AND trade_date BETWEEN '{year}0101' AND '{min(str(year)+'1231',END)}'"
            path=RAW/ep/(str(year or 'all')+'.parquet');key=path.relative_to(ROOT).as_posix()
            if key in ledger and path.exists() and sha(path)==ledger[key]['sha256']:continue
            sql=raw_query(ep,pred)
            copy_query(c,sql,path)
            n=pq.ParquetFile(path).metadata.num_rows
            ledger[key]={'source_endpoint':ep,'predicate':pred,'rows':n,'sha256':sha(path),'source_files':[p['path'] for p in obj['parts'] if p['endpoint']==ep]}
            write(ledger_path,ledger)
            print('raw',ep,year,n,flush=True)
    c.close()

if __name__=='__main__':
    baseline();external();extract()
