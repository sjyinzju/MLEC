"""Unified data-only foundation. External sources are always read-only."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import time
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.local_deps'))
import duckdb

VERSION = 'unified-data-foundation-v4.0.0'
AUDIT = ROOT / 'audit/final_data_foundation'
RAW = ROOT / 'data/raw/market/v4'
MARKET = ROOT / 'data/standardized/market/v4'
MACRO = ROOT / 'data/standardized/macro/v4'
META = ROOT / 'data/metadata/final_foundation'
SOURCE = Path('E:/QuantData')
START, END = '20140101', '20260922'
INDEX_CODES = ['000300.SH', '000001.SH', '000905.SH', '000852.SH', '000016.SH', '399001.SZ', '399006.SZ']
A_SCOPE = "((ts_code LIKE '6%.SH') OR (ts_code LIKE '0%.SZ' OR ts_code LIKE '3%.SZ'))"

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024), b''):h.update(b)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.partial')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    # Windows indexers can briefly retain a read handle on large JSON ledgers.
    for attempt in range(5):
        try:os.replace(tmp,path);break
        except PermissionError:
            if attempt==4:raise
            time.sleep(.1*(attempt+1))

def frame(path, df):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.parquet.partial');df.to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,path)

def qs(value):return "'"+str(value).replace("'","''")+"'"
def db():
    c=duckdb.connect();c.execute("SET threads=2");c.execute("SET memory_limit='2GB'");c.execute('SET enable_progress_bar=false')
    tmp=AUDIT/'temp';tmp.mkdir(parents=True,exist_ok=True)
    c.execute('SET temp_directory='+qs(tmp));c.execute('SET preserve_insertion_order=false')
    return c

def budget():
    free=shutil.disk_usage(ROOT).free
    if free<10_000_000_000:raise RuntimeError('Less than 10 GB free; preserve existing evidence and stop allocation')
    return free

def copy_query(c, sql, path):
    budget();path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.partial')
    c.execute(f'COPY ({sql}) TO {qs(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)')
    os.replace(tmp,path)

def raw_query(endpoint, where='true'):
    parts=read(AUDIT/'integrity/external_manifest.json')['parts']
    paths=[p['path'] for p in parts if p['endpoint']==endpoint]
    if not paths:raise ValueError('No source parts: '+endpoint)
    return 'SELECT * FROM read_parquet(['+','.join(qs(p) for p in paths)+'],union_by_name=true,hive_partitioning=false) WHERE '+where

def local_raw(endpoint):
    return f"read_parquet({qs(RAW/endpoint/'*.parquet')},union_by_name=true,hive_partitioning=false)"

def latest_query(endpoint, keys, where='true'):
    return f'SELECT * FROM {local_raw(endpoint)} WHERE {where} QUALIFY row_number() OVER(PARTITION BY {keys} ORDER BY _ingested_at DESC,_row_hash DESC,_batch_id)=1'
