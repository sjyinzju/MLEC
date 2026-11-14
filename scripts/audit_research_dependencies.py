"""Dependency joins and date eligibility only; does not generate features or labels."""
import collections
import csv
import datetime as dt
import json
from pathlib import Path
import duckdb

OUT=Path(r'E:\MLEC\audit');ROOT=Path(r'E:\QuantData')
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def csvout(name,rows):
    if not rows:return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
def qs(v):return "'"+str(v).replace("'","''")+"'"
snapshot=json.loads((OUT/'active_file_snapshot.json').read_text())
def src(ep):return 'read_parquet(['+','.join(qs(r[0]) for r in snapshot[ep])+'],union_by_name=true,hive_partitioning=false)'
c=duckdb.connect();c.execute("SET threads=1");c.execute("SET memory_limit='768MB'");c.execute("SET temp_directory='E:/MLEC/audit/temp_dependencies'")
registry=duckdb.connect(str(ROOT/'quant.duckdb'),read_only=True)
task=registry.execute("SELECT task_id,status,error_kind,task,rows FROM fetch_tasks WHERE endpoint='index_daily'").fetchall()
taskcodes=collections.defaultdict(list)
for ident,status,err,obj,rows in task:
    obj=json.loads(obj);code=obj['parameters'].get('ts_code');taskcodes[code].append((status,err,rows))
names={r[0]:(r[1],r[2],r[3]) for r in registry.execute('SELECT ts_code,name,market,list_date FROM canonical_index_basic').fetchall()}
actual={r[0]:(r[1],r[2],r[3]) for r in c.execute(f'SELECT ts_code,min(trade_date),max(trade_date),count(*) FROM {src("index_daily")} GROUP BY 1').fetchall()}
codecheck=[]
for code in sorted(set(names)|set(taskcodes)|set(actual)):
    wanted=code.endswith(('.SH','.SZ','.CSI','.BJ'))
    codecheck.append({'code':code,'name':names.get(code,('UNKNOWN',))[0],'market':names.get(code,('','',''))[1],'list_date':names.get(code,('','','',''))[-1],'planned':code in taskcodes,'planner_scope':wanted,'actual_rows':actual.get(code,('', '',0))[2],'actual_start':actual.get(code,('','',0))[0],'actual_end':actual.get(code,('','',0))[1],'task_status':str(taskcodes.get(code,[]))})
csvout('index_code_request_reconciliation.csv',codecheck)
save('index_code_request_summary.json',{'master_codes':len(names),'requested_codes':len(taskcodes),'actual_codes':len(actual),'in_scope_master_not_requested':[r for r in codecheck if r['planner_scope'] and r['code'] in names and not r['planned']],'requested_no_rows':[r for r in codecheck if r['planned'] and not r['actual_rows']],'unplanned_actual_codes':[r for r in codecheck if r['actual_rows'] and not r['planned']]})
# Small benchmark-only rows; verify every OHLC value is actually present.
benchmarks=['000001.SH','000300.SH','000905.SH','000852.SH','000016.SH','000688.SH','399001.SZ','399006.SZ','399303.SZ','000510.SH','899050.BJ','399300.SZ']
cal=registry.execute("SELECT DISTINCT cal_date FROM canonical_trade_cal WHERE exchange='SSE' AND is_open='1' ORDER BY 1").fetchall()
cal=[r[0] for r in cal];studycal=[d for d in cal if '20150101'<=d<='20260922'];allset=set(studycal)
rows=[];eligibility={}
for code in benchmarks:
    data=c.execute(f"SELECT ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount FROM {src('index_daily')} WHERE ts_code=? QUALIFY row_number() OVER(PARTITION BY ts_code,trade_date ORDER BY _ingested_at DESC,_row_hash DESC)=1 ORDER BY trade_date",[code]).fetchall()
    ds={r[1] for r in data};nulls={col:sum(r[i] is None for r in data) for i,col in enumerate(['code','date','open','high','low','close','pre_close','pct_chg','vol','amount'])}
    invalid=[r for r in data if any(r[i] is not None and r[i]<0 for i in [2,3,4,5,8,9]) or any(r[i] is None for i in [2,3,4,5,8,9]) or (r[4]>r[3] or not r[4]<=r[2]<=r[3] or not r[4]<=r[5]<=r[3])]
    missing=sorted(allset-ds)
    rows.append({'code':code,'name':names.get(code,('UNKNOWN',))[0],'rows':len(data),'start':min(ds) if ds else None,'end':max(ds) if ds else None,'expected_days':len(studycal),'missing_days':len(missing),'missing_dates':json.dumps(missing),'null_counts':json.dumps(nulls),'invalid_ohlcv_rows':len(invalid)})
    if code=='000300.SH':
        # Eligibility means required observations exist, not that labels/variables have been built.
        valid=[d for i,d in enumerate(studycal) if i>=60 and i+20<len(studycal) and all(x in ds for x in studycal[i-60:i+21])]
        weekly=collections.defaultdict(list)
        for day in cal:
            date=dt.datetime.strptime(day,'%Y%m%d').date();weekly[date.isocalendar()[:2]].append(day)
        weekends={max(v) for v in weekly.values()};weeks=sorted(set(valid)&weekends)
        eligibility={'raw_close_start':min(ds),'raw_close_end':max(ds),'first_internal_close_to_close_return_date':studycal[1],'first_5_return_window_date':studycal[5],'first_20_return_window_date':studycal[20],'first_60_return_window_date':studycal[60],'daily_60lookback_20forward_first':min(valid) if valid else None,'daily_60lookback_20forward_last':max(valid) if valid else None,'daily_eligible_count':len(valid),'weekly_completed_week_first':min(weeks) if weeks else None,'weekly_completed_week_last':max(weeks) if weeks else None,'weekly_eligible_count':len(weeks),'no_feature_or_label_calculation':True,'definition':'60 close-to-close returns require 61 closes including t; label requires t+1..t+20; only calendar-presence checked; weekly t is last actual open day of full ISO week.'}
csvout('benchmark_quality.csv',rows);save('research_date_eligibility.json',eligibility)
print('benchmarks',[(r['code'],r['rows'],r['missing_days']) for r in rows],flush=True)
# Relationships in bounded yearly key sets. Suspensions/listings make a full stock x day grid invalid.
rels=[];examples=[]
for year in range(2015,2027):
    for ep in ['daily','daily_basic','adj_factor','stk_limit','suspend_d']:
        c.execute(f"CREATE OR REPLACE TEMP TABLE {ep} AS SELECT DISTINCT ts_code,trade_date FROM {src(ep)} WHERE substr(trade_date,1,4)=?",[str(year)])
    for left,right in [('daily','daily_basic'),('daily','adj_factor'),('daily','stk_limit'),('daily_basic','daily'),('adj_factor','daily')]:
        count=c.execute(f'SELECT count(*) FROM {left} a ANTI JOIN {right} b USING(ts_code,trade_date)').fetchone()[0]
        susp=c.execute(f'SELECT count(*) FROM (SELECT * FROM {left} a ANTI JOIN {right} b USING(ts_code,trade_date)) a SEMI JOIN suspend_d b USING(ts_code,trade_date)').fetchone()[0]
        rels.append({'year':year,'left':left,'right':right,'left_key_count':c.execute(f'SELECT count(*) FROM {left}').fetchone()[0],'missing_matching_key':count,'same_day_suspension_key':susp})
        if count:
            for code,day in c.execute(f'SELECT * FROM {left} a ANTI JOIN {right} b USING(ts_code,trade_date) ORDER BY 1,2 LIMIT 8').fetchall():examples.append({'year':year,'left':left,'right':right,'code':code,'date':day})
    print('relationships',year,flush=True)
csvout('stock_dependency_reconciliation.csv',rels);csvout('stock_dependency_gap_examples.csv',examples)
quarantine=[];qdates=[]
for p in sorted((ROOT/'80_quarantine').rglob('*.json')):
    try:
        obj=json.loads(p.read_text(encoding='utf-8'));row={'path':str(p),'dataset':p.parent.name,'reason':obj.get('reason'),'keys':'|'.join(obj),'rows':len(obj.get('rows',[])) if isinstance(obj.get('rows'),list) else obj.get('row_count',obj.get('rows'))}
        quarantine.append(row)
        if p.parent.name=='index_daily':
            for item in obj.get('rows',[]):
                if isinstance(item,dict):qdates.append({'path':str(p),**item})
    except Exception as e:quarantine.append({'path':str(p),'error':str(e)})
csvout('quarantine_inventory.csv',quarantine);csvout('index_quarantined_rows.csv',qdates)
save('quarantine_summary.json',{'files':len(quarantine),'index_rows':len(qdates),'index_codes':dict(collections.Counter(r.get('ts_code','UNKNOWN') for r in qdates)),'rows_in_csi300':[r for r in qdates if r.get('ts_code') in ['000300.SH','399300.SZ']]})
registry.close();c.close()
