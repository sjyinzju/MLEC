"""Cached historical collection using public source interfaces, no credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import re
import sys
import json
import requests
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.common import ROOT,identity,digest,write_json,save_frame,read_json

BASE=ROOT/'data/raw/macro'
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://www.stats.gov.cn/'}

def fetch_json(url,params,path,post=False):
    if path.exists():return read_json(path)
    r=requests.post(url,data=params,headers=HEADERS,timeout=25) if post else requests.get(url,params=params,headers=HEADERS,timeout=25)
    r.raise_for_status();j=r.json();write_json(path,j);return j

def nbs_search(year,topic,max_pages=8):
    rows=[]
    for page in range(1,max_pages+1):
        params={'siteCode':'bm36000002','qt':topic,'page':page,'pageSize':20,'keyPlace':1,'timeOption':2,'startDateStr':f'{year}-01-01','endDateStr':f'{year}-12-31','sort':'dateDesc'}
        path=BASE/f'official_sources/search/nbs_{year}_{identity(topic)[:10]}_{page}.json'
        j=fetch_json('https://api.so-gov.cn/query/s',params,path,post=True)
        if not j.get('ok'):raise ValueError('NBS query failed')
        results=j.get('resultDocs',[])
        for item in results:
            d=item['data'];title=d.get('titleO','');url=d.get('url','');date=d.get('docDate','')
            if not date.startswith(str(year)):continue
            if re.match(r'(20\d{2}年|\d{1,2}月)',title) and not any(x in title for x in ['解读','统计公报','统计制度','答记者','发布会']):
                rows.append(dict(title=title,url=url,date=date,search_evidence=path.relative_to(ROOT).as_posix()))
        if page*20>=j.get('totalHits',0) or not results:break
    print('NBS',year,topic,'kept',len(rows),'hits',j.get('totalHits'),flush=True)
    return rows

def collect_nbs(start,end,topic=None):
    topics=[topic] if topic else ['居民消费价格','工业生产者出厂价格','采购经理指数','规模以上工业增加值','社会消费品零售总额','国内生产总值']
    rows=[];fail=[]
    with ThreadPoolExecutor(3) as pool:
        tasks={pool.submit(nbs_search,y,t):(y,t) for y in range(start,end+1) for t in topics}
        for future in as_completed(tasks):
            try:rows.extend(future.result())
            except Exception as exc:fail.append({'query':tasks[future],'error':type(exc).__name__})
    path=BASE/'official_sources/nbs_historical_titles.parquet'
    if path.exists():rows.extend(pd.read_parquet(path).to_dict('records'))
    d=pd.DataFrame(rows).drop_duplicates('url').sort_values('date');save_frame(path,d)
    write_json(ROOT/'audit/framework/nbs_search_failures.json',fail)
    print('Historical titles',len(d),'failures',len(fail))

def collect_historical_pages():
    d=pd.read_parquet(BASE/'official_sources/nbs_historical_titles.parquet')
    manifest=BASE/'official_sources/page_manifest.json';records=read_json(manifest)
    folder=BASE/'official_sources/pages';folder.mkdir(exist_ok=True)
    def one(url):
        if records.get(url,{}).get('status')=='ok':return url,records[url]
        try:
            r=requests.get(url,headers=HEADERS,timeout=20);r.raise_for_status();r.encoding=r.apparent_encoding
            path=folder/(identity(url)[:24]+'.html');path.write_bytes(r.content)
            return url,{'status':'ok','path':path.relative_to(ROOT).as_posix(),'sha256':digest(path),'retrieved_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'encoding':r.encoding}
        except Exception as exc:return url,{'status':'failed','error':type(exc).__name__}
    with ThreadPoolExecutor(3) as pool:
        for i,(url,record) in enumerate(pool.map(one,d.url)):
            records[url]=record
            if i%20==0:write_json(manifest,records);print('Pages',i,'/',len(d),flush=True)
    write_json(manifest,records)

def collect_eastmoney():
    jobs=['RPT_ECONOMY_RMB_LOAN','RPT_ECONOMY_INDUS_GROW','RPT_ECONOMY_TOTAL_RETAIL','RPTA_WEB_RATE']
    for report in jobs:
        rows=[];page=1
        while True:
            params={'reportName':report,'columns':'ALL','pageNumber':page,'pageSize':1000,'sortColumns':'TRADE_DATE' if report=='RPTA_WEB_RATE' else 'REPORT_DATE','sortTypes':'1','source':'WEB','client':'WEB'}
            j=fetch_json('https://datacenter-web.eastmoney.com/api/data/v1/get',params,BASE/f'third_party_sources/eastmoney/{report}_{page}.json')
            if not j.get('result'):raise ValueError(f'No result: {report}')
            rows.extend(j['result']['data'])
            if page>=j['result']['pages']:break
            page+=1
        save_frame(BASE/f'third_party_sources/eastmoney/{report}.parquet',pd.DataFrame(rows))
        print(report,len(rows),flush=True)

def collect_pboc():
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    rows=[];folder=BASE/'official_sources/pboc_lists';folder.mkdir(parents=True,exist_ok=True)
    def page(n):
        url='https://www.pbc.gov.cn/diaochatongjisi/116219/116225/'+('index.html' if n==1 else f'11871-{n}.html')
        path=folder/f'{n}.html'
        if not path.exists():
            r=requests.get(url,headers=HEADERS,timeout=20);r.raise_for_status();path.write_bytes(r.content)
        soup=BeautifulSoup(path.read_bytes(),'lxml');out=[]
        for a in soup.find_all('a',href=True):
            title=a.get_text(strip=True)
            if re.match(r'20\d{2}年',title) and any(k in title for k in ['金融统计数据报告','社会融资规模存量','社会融资规模增量']):
                out.append(dict(title=title,url=urljoin(url,a['href']),search_evidence=path.relative_to(ROOT).as_posix()))
        return out
    with ThreadPoolExecutor(3) as pool:
        for part in pool.map(page,range(1,39)):rows.extend(part)
    d=pd.DataFrame(rows).drop_duplicates('url');save_frame(BASE/'official_sources/pboc_historical_titles.parquet',d)
    manifest=BASE/'official_sources/pboc_page_manifest.json';records=read_json(manifest) if manifest.exists() else {}
    for i,r in enumerate(d.itertuples()):
        if records.get(r.url,{}).get('status')=='ok':continue
        try:
            response=requests.get(r.url,headers=HEADERS,timeout=20);response.raise_for_status();response.encoding=response.apparent_encoding
            path=BASE/'official_sources/pages'/('pboc_'+identity(r.url)[:24]+'.html');path.write_bytes(response.content)
            records[r.url]={'status':'ok','path':path.relative_to(ROOT).as_posix(),'sha256':digest(path),'retrieved_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'encoding':response.encoding}
        except Exception as exc:records[r.url]={'status':'failed','error':type(exc).__name__}
        write_json(manifest,records)
        if i%20==0:print('PBOC articles',i,'/',len(d),flush=True)
    print('PBOC titles',len(d))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['nbs','pages','eastmoney','pboc']);p.add_argument('--start',type=int,default=2014);p.add_argument('--end',type=int,default=2026);p.add_argument('--topic');a=p.parse_args()
    {'nbs':lambda:collect_nbs(a.start,a.end,a.topic),'pages':collect_historical_pages,'eastmoney':collect_eastmoney,'pboc':collect_pboc}[a.action]()
