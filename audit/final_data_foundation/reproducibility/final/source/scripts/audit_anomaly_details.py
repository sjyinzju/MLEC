"""Follow up observed zero prices/date parse flags; never changes source rows."""
import json
from pathlib import Path
import duckdb

A=Path(__file__).resolve().parents[1]/'audit';snap=json.loads((A/'active_file_snapshot.json').read_text())
def qs(v):return "'"+str(v).replace("'","''")+"'"
def src(ep):return 'read_parquet(['+','.join(qs(r[0]) for r in snap[ep])+'],union_by_name=true,hive_partitioning=false)'
def save(name,obj):(A/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
c=duckdb.connect();c.execute("SET threads=1");c.execute("SET memory_limit='768MB'");c.execute("SET temp_directory='"+str(Path(__file__).resolve().parents[1]/"audit"/"temp_anomalies").replace("'","''")+"'")
save('zero_index_close_details.json',c.execute(f"SELECT ts_code,count(DISTINCT trade_date),min(trade_date),max(trade_date) FROM {src('index_daily')} WHERE close=0 GROUP BY 1 ORDER BY 2 DESC").fetchall())
invalid=[]
for ep,col in [('disclosure_date','modify_date'),('pledge_detail','start_date'),('pledge_detail','end_date'),('pledge_detail','release_date')]:
    rows=c.execute(f"SELECT {col},count(*) FROM {src(ep)} WHERE {col} IS NOT NULL AND try_strptime({col},'%Y%m%d') IS NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 6").fetchall()
    invalid.append({'dataset':ep,'column':col,'physical_value_examples':rows,'interpretation':'format anomaly flag; source-specific meaning UNKNOWN, not automatically a failed fetch'})
save('invalid_date_examples.json',invalid)
columns=[r[0] for r in c.execute(f'DESCRIBE SELECT * FROM {src("index_dailybasic")}').fetchall() if not r[0].startswith('_')]
sql='SELECT '+','.join(f'count(*) FILTER(WHERE "{col}" IS NULL)' for col in columns)+f" FROM (SELECT * FROM {src('index_dailybasic')} WHERE ts_code='000300.SH' QUALIFY row_number() OVER(PARTITION BY ts_code,trade_date ORDER BY _ingested_at DESC,_row_hash DESC)=1)"
save('csi300_dailybasic_nulls.json',dict(zip(columns,c.execute(sql).fetchone())))
save('csi300_price_minimums.json',c.execute(f"SELECT min(open),min(high),min(low),min(close),min(vol),min(amount) FROM {src('index_daily')} WHERE ts_code='000300.SH'").fetchall())
save('csi300_dailybasic_alias_missing.json',json.loads((A/'datasets/index_dailybasic_399300.SZ_missing_dates.json').read_text()))
save('benchmark_null_price_rows.json',c.execute(f"SELECT ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount FROM {src('index_daily')} WHERE ts_code IN ('000688.SH','899050.BJ') AND (open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR pre_close IS NULL OR pct_chg IS NULL OR vol IS NULL OR amount IS NULL)").fetchall())
c.close();print('anomaly details complete',flush=True)
