"""Official historical fixings, quoted yields and SAFE currency archive."""
from pathlib import Path
import sys
import requests
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.experiment_framework.common import ROOT,write_json,read_json,digest,save_frame
BASE=ROOT/'data/raw/macro/official_sources/financial'

def collect_rates():
    BASE.mkdir(parents=True,exist_ok=True)
    def year(job):
        name,ep,y=job;rows=[];page=1;records=[]
        while True:
            params={'lang':'CN','startDate':f'{y}-01-01','endDate':f'{y}-12-31' if y<2026 else '2026-11-14','pageNum':page,'pageSize':20}
            url='https://www.chinamoney.com.cn/ags/ms/'+ep;path=BASE/f'{name}_{y}_{page}.json'
            if path.exists():j=read_json(path)
            else:
                response=requests.get(url,params=params,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.chinamoney.com.cn/chinese/sddsintigy/'},timeout=25);response.raise_for_status();j=response.json();write_json(path,j)
            if 'records' not in j:raise ValueError('Missing official records')
            rows.extend(j['records']);records.append({'url':url,'params':params,'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path)})
            info=j['data'];pages=int(info.get('pageTotal',info.get('totalPageNum',1)))
            if page>=pages:break
            page+=1
        print(name,y,len(rows),flush=True);return name,rows,records
    jobs=[(name,ep,y) for name,ep in [('shibor','cm-u-bk-shibor/ShiborHis'),('govyield','cm-u-bk-currency/SddsIntrRateGovYldHis')] for y in range(2014,2027)]
    all_rows={};sources=[]
    with ThreadPoolExecutor(2) as pool:
        for name,rows,records in pool.map(year,jobs):all_rows.setdefault(name,[]).extend(rows);sources.extend(records)
    for name,rows in all_rows.items():save_frame(BASE/f'{name}.parquet',pd.DataFrame(rows))
    write_json(BASE/'manifest.json',{'sources':sources,'retrieved_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
        'availability_policy':'official quoted date + end-of-day; not a vintage archive; conservative_release_reconstructed',
        'shibor_rule_source':'https://www.chinamoney.org.cn/chinese/bkshibor/',
        'govyield_definition':'CFETS 11:30 government real-time mean yield curve; not ChinaBond closing curve',
        'govyield_rule_source':'https://www.chinamoney.org.cn/chinese/sddsint/'})

def collect_fx():
    """SAFE labels USD as CNY per 100 USD; normalize only in supplement.py."""
    sources=ROOT/'data/raw/macro/source_references';sources.mkdir(parents=True,exist_ok=True)
    url='https://www.safe.gov.cn/safe/2020/1218/17833.html'
    page=sources/'safe_archive.html'
    if not page.exists():
        r=requests.get(url,timeout=25);r.raise_for_status();page.write_bytes(r.content)
    soup=BeautifulSoup(page.read_bytes(),'lxml')
    links=[a['href'] for a in soup.find_all('a',href=True) if a['href'].endswith('.xlsx')]
    if len(links)!=1:raise ValueError('SAFE archive changed; inspect links before selecting file')
    excel=sources/'safe_xlsx.xlsx'
    if not excel.exists():
        r=requests.get('https://www.safe.gov.cn'+links[0],timeout=25);r.raise_for_status();excel.write_bytes(r.content)
    current=sources/'safe_2026.html'
    if not current.exists():
        r=requests.post('https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do',data={'startDate':'2026-01-01','endDate':'2026-11-14'},timeout=25);r.raise_for_status();current.write_bytes(r.content)
    write_json(BASE/'fx_manifest.json',{'url':url,'archive_url':'https://www.safe.gov.cn'+links[0],
        'files':{str(p.relative_to(ROOT)):digest(p) for p in [page,excel,current]},'current_query':{'startDate':'2026-01-01','endDate':'2026-11-14'},'unit_conversion':'CNY per 100 USD / 100'})

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['rates','fx'],nargs='?',default='rates');args=p.parse_args()
    collect_rates() if args.action=='rates' else collect_fx()
