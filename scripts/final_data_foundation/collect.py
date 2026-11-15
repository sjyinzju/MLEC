"""Public evidence snapshots, bounded and content-addressed."""
import requests
from urllib.parse import urlparse
from .common import *

PUBLIC=ROOT/'data/raw/public_sources/v4'

def fetch(url,params=None,method='GET',refresh=False):
    key=hashlib.sha256(json.dumps([url,params,method],sort_keys=True).encode()).hexdigest()
    meta=PUBLIC/'requests'/f'{key}.json'
    if meta.exists() and not refresh:
        r=read(meta)
        if r['status']=='ok':
            if sha(ROOT/r['path'])!=r['sha256']:raise ValueError('Evidence hash mismatch')
            return ROOT/r['path'],r
        return None,r
    r={'url':url,'params':params,'method':method,'retrieved_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'request_id':key}
    path=None
    try:
        budget()
        response=requests.request(method,url,params=params if method=='GET' else None,data=params if method=='POST' else None,
            headers={'User-Agent':'Mozilla/5.0'},timeout=40)
        r.update(http_status=response.status_code,final_url=response.url,encoding=response.apparent_encoding or 'utf-8')
        response.raise_for_status();payload=response.content
        if len(payload)>30_000_000:raise ValueError('Response exceeds 30 MB budget')
        digest=hashlib.sha256(payload).hexdigest()
        suffix=next((s for s in ['.pdf','.xlsx','.xls','.csv','.json'] if s in url.lower()),'.html')
        path=PUBLIC/'objects'/(digest+suffix);path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(payload)
        r.update(status='ok',path=path.relative_to(ROOT).as_posix(),sha256=digest,bytes=len(payload))
    except (requests.RequestException,ValueError) as exc:r.update(status='failed',error=type(exc).__name__+': '+str(exc)[:500])
    write(PUBLIC/'attempts'/(key+'_'+hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()[:12]+'.json'),r)
    write(meta,r)
    return path,r

IDENTITY_TARGETS=[
 {'old_code':'601313.SH','new_code':'601360.SH','effective_date':'2018-02-28','publication_date':'2018-02-28','url':'https://static.cninfo.com.cn/finalpage/2018-02-28/1204434951.PDF'},
 {'old_code':'000043.SZ','new_code':'001914.SZ','effective_date':'2019-12-16','publication_date':'2019-12-16','url':'https://disc.static.szse.cn/download/disc/disk02/finalpage/2019-12-16/a5a3d55e-cc2e-42e6-91c1-ea98235594fb.PDF'},
 {'old_code':'000022.SZ','new_code':'001872.SZ','effective_date':'2018-12-26','publication_date':'2018-12-26','url':'https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF'},
 {'old_code':'300114.SZ','new_code':'302132.SZ','effective_date':'2025-02-17','publication_date':'2025-02-15','url':'https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF'}]

def definitions():
    from pypdf import PdfReader
    mappings=[]
    previous={x['old_code']:x for x in read(PUBLIC/'code_change_evidence.json')} if (PUBLIC/'code_change_evidence.json').exists() else {}
    for row in IDENTITY_TARGETS:
        p,r=fetch(row['url'])
        if p is None:continue
        text='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
        if not all(s.split('.')[0] in text for s in [row['old_code'],row['new_code']]):raise ValueError('Missing identity evidence')
        tp=p.with_suffix('.txt')
        if not tp.exists():tp.write_text(text,encoding='utf-8')
        existing=previous.get(row['old_code'],{})
        review=existing.get('review_status') if existing.get('source_sha256')==r['sha256'] and all(existing.get(k)==v for k,v in row.items()) else 'PRIMARY_DOCUMENT_REVIEW_REQUIRED'
        mappings.append({**row,'source_path':r['path'],'source_sha256':r['sha256'],'retrieved_at':r['retrieved_at'],'text_path':tp.relative_to(ROOT).as_posix(),
          'mapping_kind':'same legal listed entity, security code change; no fabricated price or factor','review_status':review})
    write(PUBLIC/'code_change_evidence.json',mappings)
    for doc in [25,26,27,28,32,95,94,181,214,100,96,99,170,124]:fetch('https://tushare.pro/document/2',{'doc_id':doc})

def mofcom_stats():
    from concurrent.futures import ThreadPoolExecutor
    url='https://data.mofcom.gov.cn/datamofcom/front/swsj/list'
    p,r=fetch(url,{'pageNumber':1,'cid':'zxtj','pageSize':15},'POST')
    if p is None:return
    count=json.loads(p.read_bytes())['pageInfo']['maxPageNum']
    def page(n):
        p,r=fetch(url,{'pageNumber':n,'cid':'zxtj','pageSize':15},'POST')
        if p is None:return []
        return [{**x,'directory_evidence':r['path']} for x in json.loads(p.read_bytes())['pageInfo']['rows']]
    with ThreadPoolExecutor(3) as pool:rows=[x for batch in pool.map(page,range(1,count+1)) for x in batch]
    write(PUBLIC/'mofcom_stats_titles.json',rows)
    targets=[x for x in rows if x['publishTimeStr']>='2014-01-01' and any(s in x['title'] for s in ['进出口','外贸','货物贸易','金融统计','外汇储备']) and '服务' not in x['title']]
    with ThreadPoolExecutor(3) as pool:
        results=list(pool.map(lambda x:fetch('https://data.mofcom.gov.cn/article'+x['url']),targets))
    print('MOFCOM directory',len(rows),'target pages',len(targets),'ok',sum(r['status']=='ok' for _,r in results),flush=True)

if __name__=='__main__':definitions()
