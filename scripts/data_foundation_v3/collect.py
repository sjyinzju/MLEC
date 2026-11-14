"""Public-source collection with immutable response bytes and attempt evidence."""
import json
import re
import threading
import shutil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
import requests
from lxml import html
from .common import ROOT,RAW,AUDIT,identity,digest,read_json,write_json,now

LOCK=threading.Lock()
CACHE_BUDGET_BYTES=2_000_000_000
MIN_FREE_BYTES=5_000_000_000
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://www.stats.gov.cn/'}

def fetch(url,params=None,method='GET',source='official',refresh=False):
    key=identity([url,params,method]);index=RAW/'requests'/f'{key}.json'
    if index.exists() and not refresh:
        r=read_json(index)
        if r['status']=='ok':
            p=ROOT/r['path']
            if digest(p)!=r['sha256']:raise ValueError('Raw evidence hash mismatch: '+str(p))
            return p,r
    rec={'request_id':key,'url':url,'params':params,'method':method,'retrieved_at':now(),'source_class':source}
    try:
        if shutil.disk_usage(ROOT).free<MIN_FREE_BYTES:raise OSError('Data collection stopped: less than 5 GB free')
        response=requests.request(method,url,params=params if method=='GET' else None,data=params if method=='POST' else None,headers=HEADERS,timeout=35)
        rec.update(http_status=response.status_code,final_url=response.url,encoding=response.apparent_encoding or 'utf-8')
        response.raise_for_status()
        content=response.content
        if len(content)>20_000_000:raise ValueError('Unexpected response over 20 MB')
        suffix='.json' if 'json' in response.headers.get('Content-Type','') else next((s for s in ['.xlsx','.xls','.pdf','.csv'] if s in url.lower()),'.html')
        p=RAW/'objects'/(identity(content.hex())+suffix);p.parent.mkdir(parents=True,exist_ok=True)
        with LOCK:
            if not p.exists():
                used=sum(x.stat().st_size for x in (RAW/'objects').iterdir() if x.is_file())
                if used+len(content)>CACHE_BUDGET_BYTES:raise OSError('2 GB v3 raw-object budget reached; retained evidence is never auto-deleted')
                p.write_bytes(content)
        rec.update(status='ok',path=p.relative_to(ROOT).as_posix(),sha256=digest(p),bytes=len(content))
    except Exception as exc:
        rec.update(status='failed',error=type(exc).__name__+': '+str(exc)[:300]);p=None
    # Every retry gets a separate immutable event, including failures.
    event=RAW/'attempts'/(key+'_'+identity(rec)[:16]+'.json')
    with LOCK:
        write_json(event,rec);write_json(index,rec)
    return p,rec

def tree(url):
    p,r=fetch(url)
    if p is None:return None,r
    return html.fromstring(p.read_bytes().decode(r['encoding'],errors='replace')),r

def nbs_search(year,topic):
    out=[]
    for page in range(1,101):
        params={'siteCode':'bm36000002','qt':topic,'page':page,'pageSize':20,'keyPlace':1,'timeOption':2,'startDateStr':f'{year}-01-01','endDateStr':f'{year}-12-31','sort':'dateDesc'}
        p,r=fetch('https://api.so-gov.cn/query/s',params,'POST')
        if p is None:break
        j=json.loads(p.read_bytes())
        if not j.get('ok'):break
        for item in j.get('resultDocs',[]):
            d=item['data'];title=d.get('titleO','')
            if d.get('docDate','').startswith(str(year)) and 'stats.gov.cn/' in d.get('url','') and any(s in d.get('url','') for s in ['/zxfb','/xwfbh/fbhwd/']) and not any(s in title for s in ['解读','答记者','制度','统计公报']):
                out.append({'title':title,'url':d['url'],'date':d['docDate'],'search_evidence':r['path'],'topic':topic})
        if page*20>=j.get('totalHits',0):break
    print('NBS search',year,topic,len(out),flush=True)
    return out

def nbs(start=2014,end=2026,topics=None):
    topics=topics or ['固定资产投资','国民经济运行']
    listing=RAW/'nbs_titles.json';rows=read_json(listing) if listing.exists() else []
    with ThreadPoolExecutor(3) as pool:
        for got in pool.map(lambda pair:nbs_search(*pair),[(y,t) for y in range(start,end+1) for t in topics]):rows.extend(got)
    rows=list({r['url']:r for r in rows}.values());write_json(listing,rows)
    targets=[r for r in rows if 'stats.gov.cn/' in r['url'] and any(s in r['url'] for s in ['/zxfb','/xwfbh/fbhwd/'])]
    with ThreadPoolExecutor(3) as pool:
        for i,(p,r) in enumerate(pool.map(lambda r:fetch(r['url']),targets)):
            if i%25==0:print('NBS pages',i,'/',len(targets),flush=True)
    return rows

def manifest():
    rows=[read_json(p) for p in sorted((RAW/'requests').glob('*.json'))]
    write_json(AUDIT/'source_manifest.json',{'generated_at':now(),'raw_root':RAW.relative_to(ROOT).as_posix(),'requests':rows})
    return rows


def credit_reprints():
    for x in read_json(ROOT/'config/data/credit_reprint_targets.json'):
        fetch(x['url'],source='contemporaneous_reprint')


def snapshot_requests():
    """Replay every explicitly recorded request, including ad-hoc source discovery.

    Successful cached bytes are hash verified and reused. Failures may be retried.
    A changed online payload gets a new content-addressed object; it is never
    asserted to be the same snapshot required by an offline reproducibility seal.
    """
    plan=read_json(ROOT/'config/data/source_requests.json')
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda x:fetch(x['url'],x.get('params'),x.get('method','GET'),x.get('source_class','official')),plan))

def financial():
    # Parameter names and one-year maximum range are from the public site component.
    fetch('https://www.chinamoney.com.cn/r/cms/chinese/chinamoney/html/currency/lpr-his-cn.html')
    for y in range(2019,2027):
        fetch('https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis',{'lang':'CN','strStartDate':f'{y}-08-20' if y==2019 else f'{y}-01-01','strEndDate':f'{y}-12-31' if y<2026 else '2026-11-14'})
    for suffix in ['currency/prr-chrt.csv','currency/prr-md.json','note/note-880.json']:
        fetch('https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/'+suffix,method='POST')
    fetch('https://www.chinamoney.com.cn/r/cms/chinese/chinamoney/html/currency/prr-chart.html')
    t,r=tree('https://www.safe.gov.cn/safe/whcb/index.html')
    urls=[urljoin(r['url'],a.get('href')) for a in t.xpath('//a[@href]') if '官方储备资产（' in a.text_content()]
    urls+=['https://www.safe.gov.cn/safe/2018/0408/8730.html']
    for u in urls:
        t,r=tree(u)
        if t is None:continue
        for a in t.xpath('//a[@href]'):
            href=urljoin(u,a.get('href'))
            if '.xls' in href:fetch(href)
    fetch('https://jingji.cctv.cn/2025/02/14/ARTI2Qy8fsueEEJNOCjrjBPu250214.shtml',source='contemporaneous_reprint')
    manifest()

def pboc_attachments():
    import pandas as pd
    rows=pd.read_parquet(ROOT/'data/raw/macro/official_sources/pboc_historical_titles.parquet')
    pages=read_json(ROOT/'data/raw/macro/official_sources/pboc_page_manifest.json');out=[]
    for x in rows.to_dict('records'):
        if '地区' in x['title']:continue
        r=pages.get(x['url'],{})
        if r.get('status')!='ok':continue
        t=html.fromstring((ROOT/r['path']).read_bytes().decode(r['encoding'],errors='replace'))
        for a in t.xpath('//a[@href]'):
            if any(e in a.get('href').lower() for e in ['.pdf','.xls']):
                out.append({'parent':x,'title':a.text_content().strip(),'url':urljoin(x['url'],a.get('href'))})
    write_json(RAW/'pboc_attachments.json',out)
    with ThreadPoolExecutor(3) as pool:
        for i,(p,r) in enumerate(pool.map(lambda x:fetch(x['url']),out)):print('PBOC attachment',i,r['status'],flush=True)
    manifest()

def pboc_legacy_tsf():
    # Before 2015 the report title did not contain 增量. The legacy collector
    # wrongly required that word and silently skipped reachable 2014 reports.
    out=[]
    for p in sorted((ROOT/'data/raw/macro/official_sources/pboc_lists').glob('*.html')):
        t=html.fromstring(p.read_bytes())
        for a in t.xpath('//a[@href]'):
            title=a.text_content().strip()
            if '社会融资规模统计数据报告' not in title or '地区' in title:continue
            td=a.xpath('ancestor::td[1]');dates=td[0].xpath('.//span[@class="hui12"]/text()') if td else []
            if dates:out.append({'title':title,'url':urljoin('https://www.pbc.gov.cn',a.get('href')),'date':dates[0].strip(),'search_evidence':p.relative_to(ROOT).as_posix()})
    out=list({x['url']:x for x in out}.values());write_json(RAW/'pboc_legacy_tsf_titles.json',out)
    with ThreadPoolExecutor(3) as pool:
        for i,(p,r) in enumerate(pool.map(lambda x:fetch(x['url']),out)):print('PBOC legacy TSF',i,r['status'],flush=True)
    return out

def safe_releases():
    rows=[]
    for page in range(1,17):
        p,r=fetch('https://www.safe.gov.cn/internet_app/search',{'q':'外汇储备规模','siteid':'safe','order':'releasetime','p':page})
        if p is None:continue
        t=html.fromstring(p.read_bytes().decode(r['encoding'],errors='replace'))
        for a in t.xpath('//a[@href]'):
            title=a.text_content().strip();url=urljoin(r['url'],a.get('href'))
            if '外汇储备规模' in title and '/safe/20' in url:rows.append({'title':title,'url':url,'search_evidence':r['path']})
        total=re.search(r'共有\s*(\d+)\s*条',t.text_content())
        if total and page*10>=int(total[1]):break
    rows=list({x['url']:x for x in rows}.values());write_json(RAW/'safe_release_titles.json',rows)
    with ThreadPoolExecutor(3) as pool:
        for i,(p,r) in enumerate(pool.map(lambda x:fetch(x['url']),rows)):
            if i%20==0:print('SAFE releases',i,len(rows),flush=True)
    return rows

def nbs_directory(base='https://www.stats.gov.cn/sj/zxfb/'):
    p,r=fetch(base+'index.html');raw=p.read_bytes().decode(r['encoding'],errors='replace')
    n=int(re.search(r'createPageHTML\((\d+),\s*0,',raw)[1]);out=[]
    def page(i):
        url=base+('index.html' if i==0 else f'index_{i}.html');t,r=tree(url);rows=[]
        if t is None:return rows
        for a in t.xpath('//a[@href]'):
            href=a.get('href');title=a.get('title') or a.text_content().strip()
            if not re.search(r'/t20\d+_\d+\.html',href):continue
            parent=a.getparent();dates=re.findall(r'20\d\d-\d\d-\d\d',parent.text_content())
            if not dates:continue
            date=dates[-1]
            if date<'2013-01-01' or not any(s in title for s in ['经济','固定资产投资','规模以上工业增加值','社会消费品零售总额']):continue
            if any(s in title for s in ['解读','民间','统计公报']):continue
            rows.append({'title':title,'url':urljoin(url,href),'date':date,'search_evidence':r['path'],'topic':'official_directory'})
        return rows
    with ThreadPoolExecutor(3) as pool:
        for i,rows in enumerate(pool.map(page,range(n))):
            out.extend(rows)
            if i%10==0:print('NBS directory',i,n,flush=True)
    listing=RAW/'nbs_titles.json';old=read_json(listing) if listing.exists() else []
    # First non-truncated anchor wins over repeated desktop/mobile labels.
    unique={}
    for x in out:
        if '...' not in x['title'] and '…' not in x['title']:unique.setdefault(x['url'],x)
    combined={x['url']:x for x in old};combined.update(unique);write_json(listing,list(combined.values()))
    with ThreadPoolExecutor(3) as pool:
        for i,(p,r) in enumerate(pool.map(lambda x:fetch(x['url']),unique.values())):
            if i%50==0:print('NBS directory pages',i,len(unique),flush=True)
    return out


def mofcom_history():
    """Follow the public CMS pagination used by the ministry's own page."""
    base='https://www.mofcom.gov.cn';t,r=tree(base+'/tjsh/qgjckqktj/index.html')
    script=t.xpath('//script[@querydata]')[0]
    query=json.loads(script.get('querydata').replace("'",'"'))
    endpoint=urljoin(base,script.get('url'));p,r=fetch(endpoint,query)
    page=html.fromstring(json.loads(p.read_text(encoding=r['encoding']))['data']['html'])
    pager=page.xpath('//div[@count]')[0];count=int(pager.get('count'));size=int(pager.get('rows'))
    out=[]
    for n in range(1,(count+size-1)//size+1):
        q={**query,'paramJson':json.dumps({'pageNo':n,'pageSize':size},separators=(',',':'))}
        p,r=fetch(endpoint,q)
        if p is None:continue
        page=html.fromstring(json.loads(p.read_text(encoding=r['encoding']))['data']['html'])
        for a in page.xpath('//a[@href]'):
            title=a.text_content().strip();dates=re.findall(r'20\d\d-\d\d-\d\d',a.getparent().text_content())
            if '进出口' in title and dates:out.append({'url':urljoin(base,a.get('href')),'title':title,'date':dates[-1],'listing_evidence':r['path']})
    out=list({x['url']:x for x in out}.values())
    def item(x):
        t,r=tree(x['url']);attachments=[]
        if t is not None:
            for node in t.xpath('//div[contains(@class,"art-con")]//img[@src] | //div[contains(@class,"art-con")]//a[@href]'):
                url=urljoin(x['url'],node.get('src') or node.get('href'))
                p,rec=fetch(url);attachments.append(rec)
        return {**x,'page_status':r['status'],'attachments':attachments}
    with ThreadPoolExecutor(3) as pool:out=list(pool.map(item,out))
    write_json(RAW/'mofcom_history_titles.json',out)
    print('MOFCOM historical bulletins',len(out),flush=True)
    return out
