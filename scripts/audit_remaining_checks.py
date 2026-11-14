"""Read-only follow-up checks for observed stock joins, leftovers, and calendar staleness."""
import collections
import csv
import datetime as dt
import json
from pathlib import Path
import duckdb
import pyarrow.parquet as pq

OUT=Path(r'E:\MLEC\audit');ROOT=Path(r'E:\QuantData')
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def csvout(name,rows):
    if not rows:return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
def qs(v):return "'"+str(v).replace("'","''")+"'"
snapshot=json.loads((OUT/'active_file_snapshot.json').read_text())
def src(ep):return 'read_parquet(['+','.join(qs(r[0]) for r in snapshot[ep])+'],union_by_name=true,hive_partitioning=false)'
c=duckdb.connect();c.execute("SET threads=1");c.execute("SET memory_limit='768MB'");c.execute("SET temp_directory='E:/MLEC/audit/temp_remaining'")
groups=collections.Counter();susp=collections.Counter();top=collections.Counter();topdays=collections.defaultdict(list)
for year in range(2015,2027):
    for ep in ['daily','daily_basic','adj_factor','stk_limit']:
        c.execute(f'CREATE OR REPLACE TEMP TABLE {ep} AS SELECT DISTINCT ts_code,trade_date FROM {src(ep)} WHERE substr(trade_date,1,4)=?',[str(year)])
    for left,right in [('daily','daily_basic'),('daily','adj_factor'),('daily','stk_limit'),('daily_basic','daily'),('adj_factor','daily')]:
        for code,n,mn,mx in c.execute(f'SELECT ts_code,count(*),min(trade_date),max(trade_date) FROM {left} a ANTI JOIN {right} b USING(ts_code,trade_date) GROUP BY 1').fetchall():
            groups[(left,right,code.rsplit('.',1)[-1])]+=n;top[(left,right,code)]+=n;topdays[(left,right,code)].extend([mn,mx])
csvout('stock_dependency_gap_by_exchange.csv',[{'left':l,'right':r,'exchange_suffix':ex,'missing_keys':n} for (l,r,ex),n in sorted(groups.items())])
csvout('stock_dependency_gap_by_code.csv',[{'left':l,'right':r,'code':code,'missing_keys':n,'first':min(topdays[(l,r,code)]),'last':max(topdays[(l,r,code)])} for (l,r,code),n in sorted(top.items())])
leftovers=[]
lineage=json.loads((OUT/'lineage_summary.json').read_text())
for item in lineage['unregistered_parquet']+lineage['partial_files']:
    path=item['path'];row={'path':path,'published_active':False}
    try:
        if '.parquet' in path:
            pf=pq.ParquetFile(path);n=0
            for b in pf.iter_batches(batch_size=32768):n+=b.num_rows
            row.update(readable=True,rows=n,fields=str(pf.schema_arrow.remove_metadata()))
        else:
            obj=json.loads(Path(path).read_text());row.update(readable=True,kind='JSON progress residual',keys='|'.join(obj))
    except Exception as e:row.update(readable=False,error=str(e))
    leftovers.append(row)
csvout('unpublished_file_checks.csv',leftovers)
reg=duckdb.connect(str(ROOT/'quant.duckdb'),read_only=True)
calendar=reg.execute("SELECT DISTINCT cal_date,is_open FROM canonical_trade_cal WHERE exchange='SSE' ORDER BY 1").fetchall()
save('staleness.json',{'client_audit_date':'2026-11-04','market_latest':'2026-09-22','calendar_latest':max(r[0] for r in calendar),'known_open_days_after_market_end':[d for d,o in calendar if o=='1' and '20260922'<d<='20261104'],'unverified_calendar_dates':['20261102','20261103','20261104'],'comment':'No extrapolation of missing calendar tail or current day market close. Offline calendar is not independently checked against current exchange announcements.'})
reg.close();c.close()
print('remaining checks complete',flush=True)
