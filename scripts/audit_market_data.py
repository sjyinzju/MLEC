"""Offline audit. Sources are opened read-only; all outputs/spill stay in E:\\MLEC.

Run with E:\\quant\\.venv\\Scripts\\python.exe -X utf8 scripts\\audit_market_data.py
No quant imports, credential loading, ingestion calls, features, or labels.
"""
import csv
import datetime as dt
import json
import time
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(r'E:\QuantData')
OUT = Path(r'E:\MLEC\audit')
(OUT / 'datasets').mkdir(exist_ok=True)
(OUT / 'temp').mkdir(exist_ok=True)
DEFS = {r[0]: r for r in json.loads((OUT/'catalog_definitions.json').read_text())}
DOCS = json.loads(Path(r'E:\quant\config\official_api_schema.json').read_text(encoding='utf-8'))
START, END = '20150101', '20260922'

def write_json(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def write_csv(name, rows):
    if not rows:
        return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (OUT/name).open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def qi(v): return '"'+v.replace('"','""')+'"'
def qs(v): return "'"+str(v).replace("'","''")+"'"
def date_sql(v):
    return f"try_strptime(cast({qi(v)} as varchar),'%Y%m%d')::date"

con=duckdb.connect(str(ROOT/'quant.duckdb'),read_only=True)
con.execute("SET TimeZone='UTC'")
con.execute("SET threads=1")
con.execute("SET memory_limit='2GB'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET temp_directory='E:/MLEC/audit/temp'")
started=dt.datetime.now(dt.timezone.utc).isoformat()
source_before=(ROOT/'quant.duckdb').stat()
tables={r[0] for r in con.execute('SHOW TABLES').fetchall()}
query_log=[]
def query(sql, params=None):
    t=time.perf_counter()
    try: return con.execute(sql,params or []).fetchall()
    finally:
        query_log.append({'sql':sql,'seconds':round(time.perf_counter()-t,3)})
        write_json('query_log.json',query_log)

con.execute('CREATE TEMP TABLE calendar AS SELECT * FROM canonical_trade_cal')
calendar=query("SELECT exchange,min(cal_date),max(cal_date),count(*),count(*) FILTER(WHERE is_open='1') FROM calendar GROUP BY exchange ORDER BY exchange")
write_json('calendar_summary.json',calendar)
open_dates={r[0].strftime('%Y%m%d') for r in query("SELECT DISTINCT try_strptime(cal_date,'%Y%m%d')::date FROM calendar WHERE exchange='SSE' AND is_open='1'")}
all_dates={r[0] for r in query("SELECT DISTINCT cal_date FROM calendar WHERE exchange='SSE'")}
window_open={d for d in open_dates if START<=d<=END}
write_csv('calendar_checks.csv',[{'check':'calendar_summary','exchange':r[0],'start':r[1],'end':r[2],'rows':r[3],'open_days':r[4]} for r in calendar])
write_json('calendar_comparison.json',query("SELECT a.cal_date,a.is_open AS sse_open,b.is_open AS szse_open FROM calendar a FULL JOIN calendar b ON a.cal_date=b.cal_date AND b.exchange='SZSE' WHERE a.exchange='SSE' AND (a.is_open<>b.is_open OR b.cal_date IS NULL) ORDER BY 1"))
write_json('calendar_pretrade_checks.json',query("SELECT exchange,count(*) AS mismatches FROM (SELECT *,max(CASE WHEN is_open='1' THEN cal_date END) OVER(PARTITION BY exchange ORDER BY cal_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_open FROM calendar) WHERE previous_open IS NOT NULL AND pretrade_date<>previous_open GROUP BY exchange"))

tasks=query("SELECT endpoint,status,error_kind,count(*),sum(rows),max(updated_at) FROM fetch_tasks GROUP BY ALL ORDER BY 1,2")
write_csv('task_status.csv',[dict(zip(['dataset','status','error_kind','tasks','reported_rows','latest_update'],r)) for r in tasks])
failed=query("SELECT task_id,endpoint,status,error_kind,task,rows,updated_at FROM fetch_tasks WHERE status<>'SUCCESS' ORDER BY endpoint,task_id")
write_csv('incomplete_tasks.csv',[dict(zip(['task_id','dataset','status','error_kind','request','reported_rows','updated_at'],r)) for r in failed])
write_json('index_task_code_status.json',query("SELECT json_extract_string(task,'$.parameters.ts_code'),status,error_kind,count(*),sum(rows),min(json_extract_string(task,'$.requested_start')),max(json_extract_string(task,'$.requested_end')) FROM fetch_tasks WHERE endpoint='index_daily' GROUP BY ALL ORDER BY 1,2"))
write_json('zero_row_tasks.json',query("SELECT endpoint,count(*),min(json_extract_string(task,'$.requested_start')),max(json_extract_string(task,'$.requested_end')) FROM fetch_tasks WHERE status='SUCCESS' AND rows=0 GROUP BY endpoint ORDER BY 1"))
write_json('quality_status.json',query('SELECT endpoint,status,count(*) FROM data_quality_results GROUP BY ALL ORDER BY 1,2'))
raw_stats=query('SELECT endpoint,state,count(*),sum(rows) FROM raw_batches GROUP BY ALL')
part_stats=query('SELECT endpoint,active,count(*),sum(rows) FROM canonical_parts GROUP BY ALL')
active={}
for ep,path,rows,h in query('SELECT endpoint,path,rows,content_hash FROM canonical_parts WHERE active ORDER BY endpoint,path'):
    active.setdefault(ep,[]).append((path,rows,h))
write_json('active_file_snapshot.json',active)
inventory=[];coverage=[];summary=[];file_checks=[]
capabilities={r[0]:r[1] for r in query('SELECT endpoint,status FROM endpoint_capabilities')}
for ep in sorted(DEFS):
    t=time.perf_counter();definition=DEFS[ep];_,category,plan,pk,df,priority=definition
    table='canonical_'+ep;paths=active.get(ep,[])
    result={'dataset':ep,'category':category,'plan':plan,'primary_key':pk,'date_field':df,'permission_probe':capabilities.get(ep,'UNKNOWN'),'active_files':len(paths),'task_status':{r[1]:r[3] for r in tasks if r[0]==ep}}
    expected={f['name']:f for f in DOCS.get(ep,{}).get('outputs',[])}
    if table not in tables or not paths:
        result.update(status='MISSING',rows=0,reason='No active canonical dataset; successful probe is insufficient.')
        for col,f in expected.items():
            inventory.append({'dataset':ep,'layer':'canonical','source':'Tushare','category':category,'column':col,'expected_type':f.get('type'),'actual_type':'MISSING','field_present':False,'rows':0,'null_count':'UNKNOWN','null_rate':'UNKNOWN','primary_key':pk,'date_field':df,'source_definition':DOCS.get(ep,{}).get('url'),'purpose':DOCS.get(ep,{}).get('title',''),'status':'MISSING'})
        coverage.append({'dataset':ep,'scope':'dataset','rows':0,'status':'MISSING','coverage_interpretation':'not downloaded / permission denied; see task_status.csv'})
        write_json(f'datasets/{ep}.json',result);summary.append(result)
        print(ep,'MISSING',flush=True);continue
    try:
        schemas={};physical_rows=0
        for path,registered_rows,h in paths:
            try:
                pf=pq.ParquetFile(path);n=pf.metadata.num_rows;physical_rows+=n
                for f in pf.schema_arrow: schemas.setdefault(f.name,set()).add(str(f.type))
                file_checks.append({'dataset':ep,'path':path,'registered_rows':registered_rows,'footer_rows':n,'row_count_matches':n==registered_rows,'footer_readable':True,'decode':'dataset query below','hash_verified':'UNKNOWN'})
            except Exception as e:
                file_checks.append({'dataset':ep,'path':path,'footer_readable':False,'error':str(e)})
        source='read_parquet(['+','.join(qs(p[0]) for p in paths)+'],union_by_name=true,hive_partitioning=false)'
        source_cols={r[0]:r[1] for r in query(f'DESCRIBE SELECT * FROM {source}')}
        splitcol=df if df in source_cols else 'month' if 'month' in source_cols else 'quarter' if 'quarter' in source_cols else None
        keys=pk.split() or ['_row_hash']
        # Bound window working sets by year when the date is part of the stable key.
        # Content identity datasets have date in the content hash. Mutable masters stay whole.
        if splitcol and (splitcol in keys or not pk) and category!='master':
            con.execute(f'CREATE OR REPLACE TEMP TABLE audited AS SELECT * FROM {source} WHERE false')
            years=query(f'SELECT DISTINCT substr(cast({qi(splitcol)} as varchar),1,4) FROM {source} ORDER BY 1')
            for (year,) in years:
                condition=f'{qi(splitcol)} IS NULL' if year is None else f'substr(cast({qi(splitcol)} as varchar),1,4)={qs(year)}'
                keys_sql=','.join(qi(k) for k in keys)
                query(f'INSERT INTO audited SELECT * FROM (SELECT * FROM {source} WHERE {condition} QUALIFY row_number() OVER(PARTITION BY _row_hash,_ingested_at ORDER BY _batch_id)=1) QUALIFY row_number() OVER(PARTITION BY {keys_sql} ORDER BY _ingested_at DESC,_row_hash DESC)=1')
        else:
            query(f'CREATE OR REPLACE TEMP TABLE audited AS SELECT * FROM {qi(table)}')
        cols={r[0]:r[1] for r in query('DESCRIBE audited')}
        n=query('SELECT count(*) FROM audited')[0][0]
        names=list(cols);agg=[]
        for col,typ in cols.items():
            q=qi(col);agg.append(f'count(*) FILTER(WHERE {q} IS NULL)')
            agg.extend([f'min({q})',f'max({q})'])
            agg.append(f'count(*) FILTER(WHERE {q} IS NOT NULL AND NOT isfinite({q}))' if typ in ('DOUBLE','FLOAT','REAL') else '0')
        stats=query('SELECT '+','.join(agg)+' FROM audited')[0]
        fields={}
        for i,col in enumerate(names):
            nulls,mn,mx,nonfinite=stats[4*i:4*i+4]
            fields[col]={'type':cols[col],'null_count':nulls,'null_rate':nulls/n if n else None,'min':mn,'max':mx,'nonfinite_count':nonfinite}
            inventory.append({'dataset':ep,'layer':'canonical','source':'Tushare','category':category,'column':col,'expected_type':expected.get(col,{}).get('type','metadata'),'actual_type':cols[col],'physical_types':'|'.join(sorted(schemas.get(col,[]))),'field_present':True,'rows':n,'null_count':nulls,'null_rate':nulls/n if n else None,'min':mn,'max':mx,'nonfinite_count':nonfinite,'primary_key':pk,'date_field':df,'active_files':len(paths),'physical_rows':physical_rows,'source_definition':DOCS.get(ep,{}).get('url'),'purpose':DOCS.get(ep,{}).get('title','')})
        missing=sorted(set(expected)-set(cols))
        for col in missing:
            inventory.append({'dataset':ep,'layer':'canonical','source':'Tushare','column':col,'expected_type':expected[col].get('type'),'actual_type':'MISSING','field_present':False,'rows':n,'null_count':n,'null_rate':1.0})
        keys=pk.split() or ['_row_hash']
        dup=query('SELECT coalesce(sum(n-1),0),count(*) FROM (SELECT count(*) n FROM audited GROUP BY '+','.join(qi(k) for k in keys)+' HAVING count(*)>1)')[0]
        content=query(f'SELECT count(*) FROM (SELECT _row_hash FROM {source} GROUP BY 1)')[0][0]
        observation=query(f'SELECT count(*) FROM (SELECT _row_hash,_ingested_at FROM {source} GROUP BY ALL)')[0][0]
        anomalies={}
        checks={}
        for col in ('open','high','low','close','pre_close','vol','amount'):
            if col in cols: checks['negative_'+col]=f'{qi(col)}<0'
        if {'open','high','low','close'}<=set(cols):
            checks['invalid_ohlc']='low>high OR open<low OR open>high OR close<low OR close>high'
            checks['zero_close']='close=0'
        if 'adj_factor' in cols: checks['invalid_adj_factor']='adj_factor IS NULL OR adj_factor<=0'
        if 'weight' in cols: checks['weight_outside_0_100']='weight<0 OR weight>100'
        if checks:
            vals=query('SELECT '+','.join(f'count(*) FILTER(WHERE {x})' for x in checks.values())+' FROM audited')[0]
            anomalies=dict(zip(checks,vals))
        # Other numeric anomalies are exposed through full-column min/max/nonfinite statistics.
        date_fields=[col for col in cols if (col.endswith('_date') or col in ('date','month','quarter')) and not col.startswith('_')]
        date_bounds={}
        for col in date_fields:
            if col in ('month','quarter'):
                date_bounds[col]={'min':fields[col]['min'],'max':fields[col]['max'],'invalid_count':'UNKNOWN (period string)'}
            else:
                d=date_sql(col)
                row=query(f'SELECT min({d}),max({d}),count(*) FILTER(WHERE {qi(col)} IS NOT NULL AND {d} IS NULL) FROM audited')[0]
                date_bounds[col]=dict(zip(['min','max','invalid_count'],row))
        datecol=df if df in cols else ('month' if 'month' in cols else 'quarter' if 'quarter' in cols else None)
        c={'dataset':ep,'scope':'dataset','rows':n,'physical_rows':physical_rows,'date_field':datecol,'missing_fields':'|'.join(missing),'logical_duplicate_rows':int(dup[0]),'physical_duplicate_observations':physical_rows-observation,'distinct_content_rows':content,'non_latest_or_reobserved_rows':physical_rows-n,'anomalies':json.dumps(anomalies),'status':'OBSERVED_NOT_FULLY_CERTIFIED'}
        if datecol:
            dates={str(r[0]) for r in query(f'SELECT DISTINCT {qi(datecol)} FROM audited WHERE {qi(datecol)} IS NOT NULL')}
            c.update(start=min(dates) if dates else None,end=max(dates) if dates else None,observed_dates=len(dates),rows_before_2016=query(f'SELECT count(*) FROM audited WHERE {qi(datecol)} < ?', ['20160101' if datecol not in ('month','quarter') else '201601' if datecol=='month' else '2016Q1'])[0][0])
            if datecol not in ('month','quarter'):
                observed=dates&window_open;missingdates=sorted(window_open-dates)
                lo,hi=c['start'],c['end'];within={d for d in window_open if lo<=d<=hi}
                c.update(expected_trade_days=len(window_open),observed_trade_days=len(observed),trade_day_coverage=len(observed)/len(window_open),missing_trade_days=len(missingdates),within_span_expected=len(within),within_span_missing=len(within-dates),nontrading_observed_dates=len({d for d in dates if d in all_dates and d not in open_dates}),coverage_interpretation='DAILY_DENSE date-level only; not symbol completeness' if ep in ('daily','daily_basic','adj_factor','stk_limit','fund_daily','fund_adj','index_daily','index_dailybasic') else 'DIAGNOSTIC ONLY: sparse/event/master/weight records are not daily requirements')
                write_json(f'datasets/{ep}_missing_dates.json',missingdates)
        # Small date/entity aggregates only; never load full data into Python.
        if datecol=='trade_date':
            dayrows=query('SELECT trade_date,count(*),'+('count(DISTINCT ts_code)' if 'ts_code' in cols else '0')+' FROM audited GROUP BY 1 ORDER BY 1')
            write_csv(f'datasets/{ep}_daily_counts.csv',[dict(zip(['date','rows','symbols'],r)) for r in dayrows])
        if ep in ('index_daily','index_dailybasic','index_weight'):
            code='index_code' if ep=='index_weight' else 'ts_code'
            symbolrows=query(f'SELECT {qi(code)},min(trade_date),max(trade_date),count(*),count(DISTINCT trade_date) FROM audited GROUP BY 1 ORDER BY 1')
            write_csv(f'{ep}_symbols.csv',[dict(zip(['code','start','end','rows','dates'],r)) for r in symbolrows])
            for codeval in ['000001.SH','000300.SH','000905.SH','000852.SH','000016.SH','000688.SH','399001.SZ','399006.SZ','399303.SZ','000510.SH','899050.BJ','399300.SZ']:
                ds={r[0] for r in query(f'SELECT DISTINCT trade_date FROM audited WHERE {qi(code)}=?',[codeval])}
                within={d for d in window_open if ds and min(ds)<=d<=max(ds)}
                row={'dataset':ep,'scope':codeval,'rows':sum(r[3] for r in symbolrows if r[0]==codeval),'date_field':'trade_date','start':min(ds) if ds else None,'end':max(ds) if ds else None,'observed_dates':len(ds),'expected_trade_days':len(window_open),'observed_trade_days':len(ds&window_open),'trade_day_coverage':len(ds&window_open)/len(window_open),'missing_trade_days':len(window_open-ds),'within_span_expected':len(within),'within_span_missing':len(within-ds),'coverage_interpretation':'MONTHLY_SNAPSHOT (daily missing not a defect)' if ep=='index_weight' else 'BENCHMARK daily against SSE open calendar'}
                coverage.append(row)
                write_json(f'datasets/{ep}_{codeval}_missing_dates.json',sorted(window_open-ds))
            if ep=='index_daily':
                export=query("SELECT * EXCLUDE(_row_hash,_batch_id,_ingested_at,_available_at,_event_date,_period_date,_announcement_date,_actual_announcement_date,_revision,_knowledge_quality,_event_available_at,_transform_version) FROM audited WHERE ts_code IN ('000300.SH','399300.SZ') ORDER BY ts_code,trade_date")
                write_csv('csi300_price_audit_rows.csv',[dict(zip([x for x in cols if not x.startswith('_')],r)) for r in export])
                write_json('benchmark_dates.json',{codeval:[r[0] for r in query('SELECT trade_date FROM audited WHERE ts_code=? ORDER BY trade_date',[codeval])] for codeval in ['000300.SH','000001.SH','000905.SH','000852.SH','000016.SH','399001.SZ','399006.SZ']})
                write_csv('index_price_issues.csv',[dict(zip(['code','date','close','pct_chg','lag_close','daily_close_return_pct'],r)) for r in query("SELECT ts_code,trade_date,close,pct_chg,lag_close,100*(close/lag_close-1) FROM (SELECT *,lag(close) OVER(PARTITION BY ts_code ORDER BY trade_date) lag_close FROM audited) WHERE (abs(close/lag_close-1)>0.25 OR (pre_close>0 AND abs(100*(close/pre_close-1)-pct_chg)>0.05)) ORDER BY ts_code,trade_date")])
            if ep=='index_weight':
                weight=query('SELECT index_code,trade_date,count(*),count(DISTINCT con_code),sum(weight),min(weight),max(weight) FROM audited GROUP BY 1,2 ORDER BY 1,2')
                write_csv('index_weight_snapshots.csv',[dict(zip(['code','date','rows','members','weight_sum','min_weight','max_weight'],r)) for r in weight])
                write_csv('index_weight_months.csv',[dict(zip(['code','month','snapshots','min_members','max_members'],r)) for r in query("SELECT index_code,substr(trade_date,1,6),count(DISTINCT trade_date),min(members),max(members) FROM (SELECT *,count(*) OVER(PARTITION BY index_code,trade_date) members FROM audited) GROUP BY 1,2 ORDER BY 1,2")])
        result.update(rows=n,physical_rows=physical_rows,distinct_content_rows=content,duplicate_observations=physical_rows-observation,reobserved_identical_content=observation-content,content_versions_beyond_latest=content-n,fields=fields,missing_fields=missing,date_bounds=date_bounds,anomalies=anomalies,coverage=c,logical_duplicate_rows=int(dup[0]),status='SCANNED',active_decode='PASS (all columns queried via latest view; footer all active files)')
        coverage.append(c)
    except Exception as e:
        result.update(status='ERROR',error=str(e));print(ep,'ERROR',str(e)[:250],flush=True)
        coverage.append({'dataset':ep,'scope':'dataset','status':'ERROR','error':str(e)})
    result['seconds']=round(time.perf_counter()-t,2)
    summary.append(result);write_json(f'datasets/{ep}.json',result)
    write_csv('dataset_inventory.csv',inventory);write_csv('dataset_coverage.csv',coverage);write_csv('active_file_checks.csv',file_checks);write_json('dataset_summary.json',summary)
    print(ep,result.get('rows'),result['status'],result['seconds'],flush=True)

source_after=(ROOT/'quant.duckdb').stat()
write_json('audit_run.json',{'started_utc':started,'ended_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True,'duckdb':duckdb.__version__,'source_before':{'bytes':source_before.st_size,'mtime_ns':source_before.st_mtime_ns},'source_after':{'bytes':source_after.st_size,'mtime_ns':source_after.st_mtime_ns},'unchanged_db_stat':(source_before.st_size,source_before.st_mtime_ns)==(source_after.st_size,source_after.st_mtime_ns),'requested_start':START,'requested_end':END,'expected_sse_open_days':len(window_open)})
con.close()
