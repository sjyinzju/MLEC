"""New official macro collection, independent of frozen v3 snapshots."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from lxml import html
from .common import *
from .collect import fetch,PUBLIC

def gac_monthlies():
    targets=[];directories=[]
    # The publisher's own selector links monthlyYYYY.html; 2026 is monthly.html.
    for year in range(2014,2027):
        url='http://english.customs.gov.cn/statics/report/monthly'+('' if year==2026 else str(year))+'.html'
        p,r=fetch(url);directories.append(r)
        if p is None:continue
        tree=html.fromstring(p.read_bytes().decode(r['encoding'],errors='replace'))
        for tr in tree.xpath('//tr'):
            label=re.sub(r'\s+',' ',tr.text_content()).strip()
            if 'Summary of Imports and Exports' not in label or 'Monthly' not in label:continue
            for a in tr.xpath('.//a[@href]'):
                targets.append({'year':year,'month_label':a.text_content().strip(),'url':urljoin(url,a.get('href')),'directory_evidence':r['path']})
    def obtain(x):
        p,r=fetch(x['url']);return {**x,**r}
    with ThreadPoolExecutor(2) as pool:rows=list(pool.map(obtain,targets))
    write(PUBLIC/'gac_monthly_sources.json',{'directories':directories,'tables':rows})
    print('GAC',len(rows),'tables',sum(x['status']=='ok' for x in rows),'downloaded',flush=True)
    return rows

def official_index_catalog():
    discovery=read(PUBLIC/'cni_source_targets.json');rows=[]
    for x in discovery['specs']:
        p,r=fetch(x['url'],x.get('request_params') or None)
        rows.append({**x,'evidence':r,'catalog_hash_agrees':r.get('sha256')==x['sha256']})
        write(PUBLIC/'cni_source_downloads.json',rows)
        time.sleep(.2)
    print('CNI',len(rows),'files',sum(x['catalog_hash_agrees'] for x in rows),'catalog hashes agree',flush=True)

def gac_preliminary():
    targets=[];directories=[]
    for year in range(2014,2027):
        url='http://english.customs.gov.cn/statics/report/preliminary'+('' if year==2026 else str(year))+'.html'
        p,r=fetch(url);directories.append(r)
        if p is None:continue
        tree=html.fromstring(p.read_bytes().decode(r['encoding'],errors='replace'))
        for tr in tree.xpath('//tr'):
            cells=tr.xpath('./td')
            if not cells:continue
            label=re.sub(r'\s+',' ',cells[0].text_content()).strip()
            if not re.search(r"China.s Total Export & Import Values \(in (CNY|USD)\)",label):continue
            for a in tr.xpath('.//a[@href]'):
                targets.append({'year':year,'currency':'CNY' if 'CNY' in label else 'USD','month_label':a.text_content().strip(),
                                'url':urljoin(url,a.get('href')),'directory_evidence':r['path']})
    def obtain(x):
        p,r=fetch(x['url']);return {**x,**r}
    with ThreadPoolExecutor(2) as pool:rows=list(pool.map(obtain,targets))
    write(PUBLIC/'gac_preliminary_sources.json',{'directories':directories,'tables':rows})
    print('GAC preliminary',len(rows),'tables',sum(x['status']=='ok' for x in rows),'downloaded',flush=True)

if __name__=='__main__':gac_monthlies()
