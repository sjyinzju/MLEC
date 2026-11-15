"""Fill observed-security/date moneyflow gaps from retained provider responses."""
import time
from concurrent.futures import ThreadPoolExecutor
from .common import *
from .provider import client,request,API_RAW


def collect():
    targets=pd.read_parquet(AUDIT/'source_reconciliation/moneyflow_gap_targets.parquet')
    master=pd.read_parquet(MARKET/'stock_master_history.parquet').set_index('ts_code').instrument_id.to_dict()
    jobs=[]
    for month in range(1,13):
        day=pd.Timestamp(2014,month,1)
        jobs.append({'start_date':day.strftime('%Y%m%d'),'end_date':(day+pd.offsets.MonthEnd()).strftime('%Y%m%d')})
    jobs += [{'ts_code':master[r.ts_code].removeprefix('CN-EQUITY-'),'start_date':r.start_date,'end_date':r.end_date} for r in targets.itertuples(index=False)]
    def job(params):
        adapter,catalog=client();receipts=[];seen=set()
        for offset in range(0,200001,5000):
            r=request(adapter,catalog,'moneyflow',{**params,'limit':5000,'offset':offset});receipts.append(r)
            if r['status']!='ok':break
            payload=read(ROOT/r['path']);d=pd.DataFrame(payload['items'],columns=payload['fields'])
            if len(d):
                assert d.trade_date.between(params['start_date'],params['end_date']).all()
                keys=set(map(tuple,d[['ts_code','trade_date']].to_numpy()))
                assert not keys&seen,'Repeated pagination keys'
                seen |= keys
            if len(d)<5000:break
            time.sleep(1.1)
        else:raise ValueError('Unexpected moneyflow request size')
        time.sleep(1.1)
        return receipts
    path=API_RAW/'moneyflow_supplement_requests.json'
    receipts=read(path) if path.exists() else [];known={r['request_id'] for r in receipts}
    with ThreadPoolExecutor(3) as pool:
        for i,group in enumerate(pool.map(job,jobs),1):
            receipts.extend(r for r in group if r['request_id'] not in known);known.update(r['request_id'] for r in group)
            write(path,receipts)
            if i%25==0:print('Moneyflow target requests',i,'/',len(jobs),flush=True)


def promote():
    # Only formerly missing observed-security dates are added, never an alternate
    # unmarked revision of existing source observations.
    master=pd.read_parquet(MARKET/'stock_master_history.parquet')[['ts_code','instrument_id']].drop_duplicates().set_index('ts_code').instrument_id.to_dict()
    parts=[]
    for p in sorted((AUDIT/'missing_records/stock_moneyflow').glob('*.parquet')):
        d=pd.read_parquet(p);parts.append(d[['instrument_id','trade_date']])
    targets=pd.concat(parts,ignore_index=True)
    target_path=API_RAW/'moneyflow_original_gap_keys.parquet'
    if not target_path.exists():frame(target_path,targets)
    else:targets=pd.read_parquet(target_path)
    wanted=set(map(tuple,targets.to_numpy()));frames=[]
    for r in read(API_RAW/'moneyflow_supplement_requests.json'):
        if r['status']!='ok':continue
        assert sha(ROOT/r['path'])==r['sha256']
        payload=read(ROOT/r['path']);d=pd.DataFrame(payload['items'],columns=payload['fields'])
        if d.empty:continue
        keys=zip(d.ts_code.map(master),d.trade_date)
        d=d.loc[[key in wanted for key in keys]].copy()
        if d.empty:continue
        d['_row_hash']=[hashlib.sha256(json.dumps(x,ensure_ascii=False,default=str).encode()).hexdigest() for x in d.to_dict('records')]
        d['_batch_id']=r['request_id'];d['_ingested_at']=pd.Timestamp(payload['fetched_at']);d['_available_at']=d['_ingested_at'];d['_source_evidence']=r['path'];frames.append(d)
    d=pd.concat(frames,ignore_index=True).sort_values(['_ingested_at','_batch_id']).drop_duplicates(['ts_code','trade_date'],keep='last')
    for year,g in d.groupby(d.trade_date.str[:4]):frame(RAW/'moneyflow'/('api_gap_'+year+'.parquet'),g.sort_values(['ts_code','trade_date']))
    result={'original_missing_observed_dates':len(wanted),'supplement_rows':len(d),'unfilled_observed_dates':len(wanted)-len(d),
      'years':d.trade_date.str[:4].value_counts().sort_index().to_dict(),'quality':'Provider-classified order flow, latest retrieved version; not certified original vintage or true investor cash flow.',
      'raw_request_ledger':(API_RAW/'moneyflow_supplement_requests.json').relative_to(ROOT).as_posix()}
    write(AUDIT/'issue_closure/moneyflow_supplement.json',result);print(result,flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['collect','promote']);a=p.parse_args()
    collect() if a.action=='collect' else promote()
