"""Read-only storage/lineage audit, deterministic raw and retired-file sampling."""
import collections
import concurrent.futures
import csv
import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

OUT=Path(__file__).resolve().parents[1]/'audit';ROOT=Path(r'E:\QuantData')
def save(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def csvout(name,rows):
    if not rows:return
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
con=duckdb.connect(str(ROOT/'quant.duckdb'),read_only=True)
con.execute("SET threads=1");con.execute("SET memory_limit='512MB'")
raw={r[0]:(r[1],r[2],r[3]) for r in con.execute('SELECT path,endpoint,rows,state FROM raw_batches').fetchall()}
parts={r[0]:(r[1],r[2],r[3],r[4]) for r in con.execute('SELECT path,endpoint,rows,active,content_hash FROM canonical_parts').fetchall()}
active={p:v for p,v in parts.items() if v[2]}
seenraw=set();seenpart=set();unregistered=[];otherdb=[];partials=[];qlib=[];samples=collections.defaultdict(list);rawpaths=[];physical=collections.Counter()
with (OUT/'file_manifest.csv').open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f):
        path=r['path'];p=Path(path)
        if path in raw:seenraw.add(path);rawpaths.append(path)
        if path in parts:seenpart.add(path)
        if r['extension']=='.parquet' and r['layer'] in ('00_raw','10_canonical'):
            rel=p.relative_to(ROOT).parts;ep=rel[2] if rel[0]=='00_raw' else rel[1];layer=rel[0]
            physical[(ep,layer)]+=1
            if path not in raw and path not in parts: unregistered.append({'path':path,'layer':layer,'dataset':ep,'status':'UNREGISTERED'})
            if layer=='10_canonical' and path not in active:
                arr=samples[(ep,'retired')];arr.append(path)
                if len(arr)>3:arr[1]=arr[-1];arr.pop()
        if r['extension'] in ('.duckdb','.sqlite'):otherdb.append(path)
        if r['extension']=='.partial':partials.append(r)
        if r['layer']=='40_qlib' and p.name=='manifest.json':qlib.append(path)
save('lineage_summary.json',{'registered_raw':len(raw),'raw_present':len(seenraw),'raw_missing':sorted(set(raw)-seenraw),'registered_canonical':len(parts),'canonical_present':len(seenpart),'canonical_missing':sorted(set(parts)-seenpart),'active_missing':sorted(set(active)-seenpart),'unregistered_parquet':unregistered,'partial_files':partials})
csvout('physical_dataset_files.csv',[{'dataset':ep,'layer':layer,'files':n} for (ep,layer),n in sorted(physical.items())])
print('lineage complete',len(rawpaths),'raw footers next',flush=True)
def check_raw(path):
    ep,n,state=raw[path]
    row={'path':path,'dataset':ep,'registry_rows':n,'state':state}
    try:
        pf=pq.ParquetFile(path);row.update(footer_rows=pf.metadata.num_rows,readable=True,row_count_matches=n==pf.metadata.num_rows,columns=len(pf.schema_arrow))
        # Record schema signatures to expose drift without duplicating full field lists per file.
        row['schema_hash']=hashlib.sha256(str(pf.schema_arrow.remove_metadata()).encode()).hexdigest()
    except Exception as e:row.update(readable=False,error=str(e))
    return row
raw_summary=collections.defaultdict(lambda:{'files':0,'footer_rows':0,'bad_footers':0,'row_count_mismatches':0,'schemas':collections.Counter()})
issues=[];sample_raw=collections.defaultdict(list)
with (OUT/'raw_file_checks.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=['path','dataset','registry_rows','state','footer_rows','readable','row_count_matches','columns','schema_hash','error']);w.writeheader()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for i,row in enumerate(pool.map(check_raw,rawpaths,chunksize=100)):
            w.writerow(row);s=raw_summary[row['dataset']];s['files']+=1;s['footer_rows']+=row.get('footer_rows',0);s['bad_footers']+=not row['readable'];s['row_count_mismatches']+=row.get('row_count_matches',True)==False;s['schemas'][row.get('schema_hash','ERROR')]+=1
            if not row['readable'] or not row.get('row_count_matches',True):issues.append(row)
            arr=sample_raw[row['dataset']];arr.append(row['path'])
            if len(arr)>3:arr[1]=arr[-1];arr.pop()
            if (i+1)%50000==0:print('raw footers',i+1,flush=True)
save('raw_integrity_summary.json',raw_summary);save('raw_integrity_issues.json',issues)
print('raw footers done; active hashes',len(active),flush=True)
def check_hash(item):
    path,(ep,n,active_flag,h)=item
    try:
        hasher=hashlib.sha256()
        with open(path,'rb') as f:
            for chunk in iter(lambda:f.read(4*1024*1024),b''):hasher.update(chunk)
        return {'dataset':ep,'path':path,'hash_matches':hasher.hexdigest()==h}
    except Exception as e:return {'dataset':ep,'path':path,'hash_matches':False,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:hashes=list(pool.map(check_hash,active.items()))
csvout('active_file_hashes.csv',hashes)
save('active_hash_summary.json',{'files':len(hashes),'mismatches':[r for r in hashes if not r['hash_matches']]})
decode=[]
for ep,paths in sample_raw.items():samples[(ep,'raw')]=paths
for (ep,kind),paths in sorted(samples.items()):
    for path in sorted(set(paths)):
        row={'dataset':ep,'layer':kind,'path':path}
        try:
            pf=pq.ParquetFile(path);n=0
            for b in pf.iter_batches(batch_size=32768):n+=b.num_rows
            row.update(full_decode=True,rows=n,fields=str(pf.schema_arrow.remove_metadata()))
        except Exception as e:row.update(full_decode=False,error=str(e))
        decode.append(row)
csvout('sample_file_decode.csv',decode)
print('hashes and sample decode done',flush=True)
# Inspect auxiliary DB schemas without opening writable connections or executing source code.
dbrows=[]
for path in otherdb:
    row={'path':path,'role':'primary registry' if path==str(ROOT/'quant.duckdb') else 'backup/frozen registry/PIT test scratch/audit evidence; not independent market feed'}
    try:
        if path.endswith('.duckdb'):
            c=duckdb.connect(path,read_only=True);ts=c.execute('SHOW TABLES').fetchall();row['tables']=len(ts);row['table_names']='|'.join(x[0] for x in ts);c.close()
        else:
            c=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True);ts=c.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall();row['tables']=len(ts);row['schemas']=json.dumps(ts);row['quick_check']=c.execute('PRAGMA quick_check').fetchone()[0];c.close()
        row['open_read_only']='PASS';row['full_content_check']='UNKNOWN (not all backup views/data decoded)'
    except Exception as e:row.update(open_read_only='ERROR',error=str(e))
    dbrows.append(row)
csvout('database_inventory.csv',dbrows)
qrows=[]
for path in qlib:
    obj=json.loads(Path(path).read_text());qrows.append({'path':path,**{k:v for k,v in obj.items() if k not in ('files','limitations','skipped')},'manifest_file_count':len(obj.get('files',{})),'validation':'UNKNOWN; existing derived export; not course input','skipped':obj.get('skipped')})
save('qlib_inventory.json',qrows)
con.close()
