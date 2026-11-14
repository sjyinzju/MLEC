"""Index date coverage relative to local calendar, plus code identity and raw history checks."""
import bisect
import collections
import csv
import json
from pathlib import Path
import duckdb

OUT=Path(__file__).resolve().parents[1]/'audit';ROOT=Path(r'E:\QuantData')
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def csvout(name,rows):
    if not rows:return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
def qs(v):return "'"+str(v).replace("'","''")+"'"
snap=json.loads((OUT/'active_file_snapshot.json').read_text())
def src(ep):return 'read_parquet(['+','.join(qs(r[0]) for r in snap[ep])+'],union_by_name=true,hive_partitioning=false)'
reg=duckdb.connect(str(ROOT/'quant.duckdb'),read_only=True)
c=duckdb.connect();c.execute("SET threads=1");c.execute("SET memory_limit='768MB'");c.execute("SET temp_directory='"+str(Path(__file__).resolve().parents[1]/"audit"/"temp_indices").replace("'","''")+"'")
cal=[r[0] for r in reg.execute("SELECT DISTINCT cal_date FROM canonical_trade_cal WHERE exchange='SSE' AND is_open='1' AND cal_date BETWEEN '20150101' AND '20260922' ORDER BY 1").fetchall()]
c.execute('CREATE TEMP TABLE cal(day VARCHAR)');c.executemany('INSERT INTO cal VALUES (?)',[(x,) for x in cal])
total=collections.Counter();outside=collections.Counter();bounds={}
for year in range(2015,2027):
    rows=c.execute(f"SELECT ts_code,min(trade_date),max(trade_date),count(DISTINCT trade_date) FILTER(WHERE day IS NOT NULL),count(DISTINCT trade_date) FILTER(WHERE day IS NULL) FROM {src('index_daily')} a LEFT JOIN cal b ON a.trade_date=b.day WHERE substr(trade_date,1,4)=? GROUP BY ts_code",[str(year)]).fetchall()
    for code,lo,hi,n,out in rows:
        total[code]+=n;outside[code]+=out
        old=bounds.get(code,(lo,hi));bounds[code]=(min(lo,old[0]),max(hi,old[1]))
coverage=[]
for code,(lo,hi) in sorted(bounds.items()):
    expected=bisect.bisect_right(cal,hi)-bisect.bisect_left(cal,lo)
    coverage.append({'code':code,'start':lo,'end':hi,'expected_sse_days_within_observed_span':expected,'observed_sse_days':total[code],'within_span_missing_sse_days':expected-total[code],'outside_sse_calendar_dates':outside[code],'interpretation':'diagnostic, not automatic error: overseas exposure/calendar, start/end policy and launch dates require interpretation'})
csvout('all_index_calendar_diagnostics.csv',coverage)
bench=['000001.SH','000300.SH','000905.SH','000852.SH','000016.SH','000688.SH','399001.SZ','399006.SZ','399303.SZ','000510.SH','899050.BJ','399300.SZ']
master=reg.execute("SELECT ts_code,name,market,publisher,base_date,list_date FROM canonical_index_basic WHERE ts_code IN ("+','.join(qs(s) for s in bench)+') ORDER BY 1').fetchall()
csvout('benchmark_master_definitions.csv',[dict(zip(['code','name','market','publisher','base_date','list_date'],r)) for r in master])
sql=f"SELECT * FROM {src('index_daily')} WHERE ts_code IN ('000300.SH','399300.SZ') QUALIFY row_number() OVER(PARTITION BY ts_code,trade_date ORDER BY _ingested_at DESC,_row_hash DESC)=1"
c.execute('CREATE TEMP TABLE twins AS '+sql)
save('csi300_code_comparison.json',c.execute("SELECT count(*),count(*) FILTER(WHERE a.close<>b.close),max(abs(a.close-b.close)),count(*) FILTER(WHERE a.amount<>b.amount OR a.vol<>b.vol) FROM twins a JOIN twins b ON a.trade_date=b.trade_date WHERE a.ts_code='000300.SH' AND b.ts_code='399300.SZ'").fetchall())
paths=reg.execute("SELECT r.path FROM raw_batches r JOIN fetch_tasks t USING(task_id) WHERE r.endpoint='index_daily' AND json_extract_string(t.task,'$.parameters.ts_code') IN ('000300.SH','399300.SZ')").fetchall()
source='read_parquet(['+','.join(qs(r[0]) for r in paths)+'],union_by_name=true,hive_partitioning=false)'
save('csi300_raw_bounds.json',{'files':len(paths),'actual_query':c.execute(f'SELECT ts_code,min(trade_date),max(trade_date),count(*) FROM {source} GROUP BY ts_code').fetchall()})
save('all_index_calendar_summary.json',{'actual_codes':len(coverage),'codes_with_internal_sse_day_gaps':sum(r['within_span_missing_sse_days']>0 for r in coverage),'codes_with_outside_sse_dates':sum(r['outside_sse_calendar_dates']>0 for r in coverage),'not_all_indices_share_the_sse_calendar':True})
reg.close();c.close();print('index scope checks complete',flush=True)
