"""Targeted supplements, using existing credential-safe read-only provider."""
import argparse
import pandas as pd
from .common import OUT, ROOT, write
from scripts.final_data_foundation.provider import client, request

def payload(r):
    import json
    p = json.loads((ROOT/r['path']).read_text(encoding='utf8'))
    return pd.DataFrame(p['items'], columns=p['fields'])

def collect():
    a, catalog = client(); receipts = []
    end=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y%m%d')
    def fetch(ep, params):
        r = request(a, catalog, ep, params); receipts.append(r)
        write(OUT/'source_requests.json', receipts)
        if r['status'] != 'ok': return pd.DataFrame()
        return payload(r)
    calendar=fetch('trade_cal',dict(exchange='SSE',start_date='20140101',end_date=end))
    if len(calendar):
        (OUT/'sources').mkdir(parents=True,exist_ok=True)
        calendar.to_parquet(OUT/'sources/trade_calendar.parquet',index=False)
    for code in ['000985.CSI', '000300.SH', '000905.SH', '000852.SH']:
        f = fetch('index_daily', dict(ts_code=code, start_date='20140101', end_date=end))
        if len(f):
            f['provider_code'] = f.ts_code
            f['ts_code'] = f.ts_code.replace({'000985.CSI':'000985.SH'})
            p=OUT/'sources'/('index_'+code+'.parquet'); p.parent.mkdir(parents=True,exist_ok=True); f.to_parquet(p,index=False)
    for status in ['L', 'D', 'P']:
        f=fetch('stock_basic',dict(exchange='',list_status=status))
        if len(f): f.to_parquet(OUT/'sources'/('stock_basic_'+status+'.parquet'),index=False)
    for code in ['000300.SH','000905.SH','000852.SH']:
        for start,stop in [('20140101','20150131'),('20260901',end)]:
            f=fetch('index_weight',dict(index_code=code,start_date=start,end_date=stop))
            if len(f):f.to_parquet(OUT/'sources'/f'weights_{code}_{start}.parquet',index=False)
    idx=pd.read_parquet(OUT/'sources/index_000985.CSI.parquet')
    # Extend only the actual missing tail; never copy the external lake.
    from .common import BASE,db
    c=db();last=c.execute('SELECT max(trade_date) FROM read_parquet(?)',[str(BASE/'stock_daily_observations/*.parquet')]).fetchone()[0];c.close()
    for date in sorted(idx.loc[idx.trade_date.gt(last),'trade_date']):
        for ep in ['daily','daily_basic','adj_factor','suspend_d']:
            if (OUT/'sources'/ep/(date+'.parquet')).exists():continue
            parts=[]
            for offset in range(0,30000,5000):
                f=fetch(ep,dict(trade_date=date,limit=5000,offset=offset))
                if f.empty:break
                if not f.trade_date.eq(date).all():raise ValueError('Provider ignored date')
                parts.append(f)
                if len(f)<5000:break
            if parts:
                f=pd.concat(parts,ignore_index=True)
                if ep!='suspend_d' and f.duplicated(['ts_code','trade_date']).any():raise ValueError('Provider ignored pagination')
                f=f.drop_duplicates()
                p=OUT/'sources'/ep/(date+'.parquet');p.parent.mkdir(parents=True,exist_ok=True);f.to_parquet(p,index=False)
        action_path=OUT/'sources/dividend'/(date+'.parquet')
        if not action_path.exists():
            action=fetch('dividend',dict(ex_date=date))
            if len(action):action_path.parent.mkdir(parents=True,exist_ok=True);action.to_parquet(action_path,index=False)
        print('tail collected',date,flush=True)

if __name__=='__main__': collect()
