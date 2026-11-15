"""Read-only API requests through the existing credential-safe quant adapter.

No quant lake/registry/ingestion writer is constructed; every output stays here.
"""
from .common import *

API_RAW=ROOT/'data/raw/market/provider_supplements/v4'

def client():
    sys.path.insert(0,'E:/quant/src')
    from quant.config import load_settings
    from quant.data.sources.tushare import TushareAdapter
    from quant.data.schemas.catalog import load_catalog
    settings=load_settings(data_root=ROOT/'data/raw/market/provider_supplements/v4')
    settings.max_attempts=2
    return TushareAdapter(settings),load_catalog()

def request(adapter,catalog,endpoint,params,refresh=False):
    key=hashlib.sha256(json.dumps([endpoint,params],sort_keys=True).encode()).hexdigest()
    path=API_RAW/'requests'/f'{key}.json'
    if path.exists() and not refresh:
        r=read(path)
        if r['status']=='ok' and sha(ROOT/r['path'])!=r['sha256']:raise ValueError('API snapshot hash changed')
        return r
    from quant.data.sources.tushare import SourceError
    r={'endpoint':endpoint,'params':params,'request_id':key,'source':'https://api.tushare.pro','retrieved_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat()}
    try:
        result=adapter.fetch(catalog[endpoint],params)
        payload={'fields':result.fields,'items':result.rows,'fetched_at':result.fetched_at.isoformat()}
        digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        obj=API_RAW/'objects'/f'{digest}.json'
        if not obj.exists():write(obj,payload)
        r.update(status='ok',rows=len(result.rows),path=obj.relative_to(ROOT).as_posix(),sha256=sha(obj))
    except SourceError as exc:r.update(status='failed',error_kind=exc.kind,error=str(exc),retryable=exc.retryable)
    write(API_RAW/'attempts'/(key+'_'+hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()[:12]+'.json'),r)
    write(path,r);print(endpoint,params,r['status'],r.get('rows'),r.get('error_kind',''),flush=True)
    return r

def warmup_probe():
    adapter,catalog=client()
    for endpoint,params in [('index_daily',{'ts_code':'000300.SH','start_date':'20140101','end_date':'20141231'}),
                            ('daily',{'trade_date':'20140102'}),('daily_basic',{'trade_date':'20140102'}),('adj_factor',{'trade_date':'20140102'}),
                            ('suspend_d',{'trade_date':'20140102'}),('index_weight',{'index_code':'000300.SH','start_date':'20140101','end_date':'20140131'})]:
        request(adapter,catalog,endpoint,params)

def warmup():
    """Paginated 2014 history. Stop on denied access, repeats or out-of-range data."""
    adapter,catalog=client();receipts=[]
    for code in INDEX_CODES:
        for ep in ['index_daily','index_dailybasic']:
            receipts.append(request(adapter,catalog,ep,{'ts_code':code,'start_date':'20140101','end_date':'20141231'}))
    for month in range(1,13):
        first=pd.Timestamp(2014,month,1);last=first+pd.offsets.MonthEnd(0)
        active=['daily','daily_basic','adj_factor','stk_limit','suspend_d']
        offset=0;seen={ep:set() for ep in active}
        while active:
            following=[]
            for ep in active:
                params={'start_date':first.strftime('%Y%m%d'),'end_date':last.strftime('%Y%m%d'),'limit':5000,'offset':offset}
                r=request(adapter,catalog,ep,params);receipts.append(r)
                if r['status']!='ok':continue
                payload=read(ROOT/r['path']);df=pd.DataFrame(payload['items'],columns=payload['fields'])
                if len(df):
                    if not df.trade_date.between(params['start_date'],params['end_date']).all():raise ValueError('API ignored date range: '+ep)
                    keys=set(tuple(x) for x in df[['ts_code','trade_date']].to_numpy())
                    if keys and keys<=seen[ep]:raise ValueError('API ignored pagination: '+ep)
                    seen[ep]|=keys
                if len(df)>=5000:following.append(ep)
            active=following;offset+=5000
            if offset>200000:raise ValueError('Unexpected month size')
        write(AUDIT/'source_reconciliation/warmup_requests.json',receipts)
        print('warmup month complete',month,flush=True)

def promote_warmup():
    """Preserve API evidence; generate a separately named raw provider snapshot."""
    requests=[read(p) for p in (API_RAW/'requests').glob('*.json')]
    ledger={}
    for ep in ['daily','daily_basic','adj_factor','stk_limit','suspend_d','index_daily','index_dailybasic']:
        frames=[]
        for r in requests:
            if r['endpoint']!=ep or r['status']!='ok':continue
            payload=read(ROOT/r['path']);d=pd.DataFrame(payload['items'],columns=payload['fields'])
            if d.empty or 'trade_date' not in d:continue
            d=d[d.trade_date.between('20140101','20141231')].copy()
            if d.empty:continue
            d['_row_hash']=[hashlib.sha256(json.dumps(row,ensure_ascii=False,default=str).encode()).hexdigest() for row in d.to_dict('records')]
            d['_batch_id']=r['request_id'];d['_ingested_at']=pd.Timestamp(payload['fetched_at']);d['_available_at']=d['_ingested_at']
            d['_source_evidence']=r['path'];frames.append(d)
        if not frames:continue
        d=pd.concat(frames,ignore_index=True).sort_values(['_ingested_at','_batch_id']).drop_duplicates('_row_hash',keep='first')
        p=RAW/ep/'api_2014.parquet';frame(p,d)
        ledger[ep]={'path':p.relative_to(ROOT).as_posix(),'rows':len(d),'sha256':sha(p),'availability':'retrieval-only; opt-in quote reconstruction is separate'}
    write(AUDIT/'integrity/api_warmup_promotion.json',ledger)

if __name__=='__main__':warmup_probe()
