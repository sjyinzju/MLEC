"""Bounded, cached collection; credentials are neither needed nor read."""
import argparse
import json
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.experiment_framework.common import ROOT, digest, identity, read_json, save_frame, write_json
import pandas as pd

def extract_local():
    sys.path.insert(0, str(ROOT/'.local_deps'))
    import duckdb
    source = Path('E:/QuantData/quant.duckdb')
    before = (source.stat().st_size, source.stat().st_mtime_ns)
    with duckdb.connect(str(source), read_only=True) as conn:
        files = conn.execute("SELECT endpoint,path,rows,content_hash FROM canonical_parts WHERE active AND endpoint IN ('cn_cpi','cn_ppi','cn_m','cn_pmi','sf_month','shibor','cn_schedule') ORDER BY endpoint,path").df()
    audit=[]
    for ep, parts in files.groupby('endpoint'):
        frames=[]
        for r in parts.itertuples():
            h=digest(r.path)
            if h != r.content_hash: raise ValueError(f'Source hash mismatch: {r.path}')
            d=pd.read_parquet(r.path); d['_source_file']=r.path; frames.append(d)
            audit.append(dict(endpoint=ep,path=r.path,sha256=h,rows=len(d)))
        d=pd.concat(frames,ignore_index=True).drop_duplicates(['_row_hash','_ingested_at'])
        save_frame(ROOT/f'data/raw/macro/third_party_sources/quant/{ep}.parquet',d)
    after=(source.stat().st_size,source.stat().st_mtime_ns)
    if after != before: raise RuntimeError('Source registry changed')
    write_json(ROOT/'audit/framework/quant_extraction.json', {'source_stat':before,'unchanged':True,'files':audit})
    print('Extracted', len(audit), 'registered files; source registry unchanged')

def collect_pages(limit=20):
    import requests
    from bs4 import BeautifulSoup
    raw=ROOT/'data/raw/macro/original_submissions/v1'
    d=pd.read_parquet(raw/'deliverables/macro_raw.parquet')
    # Priority: semantic errors, then archived monthly release evidence.
    priority=['new_rmb_loans','industrial_va_yoy','retail_sales_ytd_yoy','pmi_new_orders','cpi_yoy','ppi_yoy','m2_yoy']
    urls=[]
    for sid in priority:
        urls.extend(d.loc[d.series_id.eq(sid),'source_url'].dropna().unique())
    urls=list(dict.fromkeys(u for u in urls if 'stats.gov.cn/' in u or 'pbc.gov.cn/' in u))
    folder=ROOT/'data/raw/macro/official_sources/pages';folder.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/'data/raw/macro/official_sources/page_manifest.json'
    records=read_json(manifest) if manifest.exists() else {}
    attempted=0
    for url in urls:
        if url in records and records[url].get('status')=='ok': continue
        if attempted >= limit: break
        attempted+=1; key=identity(url)[:24]; retrieved=pd.Timestamp.now(tz='Asia/Shanghai').isoformat()
        try:
            response=requests.get(url,timeout=20);response.raise_for_status()
            response.encoding=response.apparent_encoding
            soup=BeautifulSoup(response.text,'html.parser')
            text=soup.get_text(' ',strip=True)
            if len(text)<200: raise ValueError('Response too short')
            path=folder/f'{key}.html';path.write_bytes(response.content)
            records[url]={'status':'ok','path':path.relative_to(ROOT).as_posix(),'sha256':digest(path),'retrieved_at':retrieved,'encoding':response.encoding}
        except Exception as exc:
            records[url]={'status':'failed','error':type(exc).__name__,'retrieved_at':retrieved}
        write_json(manifest,records)
    print('Page status:',pd.Series([v['status'] for v in records.values()]).value_counts().to_dict())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['local','pages']);p.add_argument('--limit',type=int,default=20);a=p.parse_args()
    extract_local() if a.action=='local' else collect_pages(a.limit)
