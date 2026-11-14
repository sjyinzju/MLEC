"""Read-only discovery; writes only course audit artifacts."""
import ast
import collections
import csv
import json
import os
from pathlib import Path
import duckdb

OUT = Path(__file__).resolve().parents[1]/'audit'
root = Path(r'E:\QuantData')
def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

con = duckdb.connect(str(root / 'quant.duckdb'), read_only=True)
tables = con.execute('SHOW TABLES').fetchall()
db = {}
for (name,) in tables:
    if name.startswith('canonical_') and name != 'canonical_parts':
        continue
    desc = con.execute(f'DESCRIBE "{name}"').fetchall()
    db[name] = {'schema': desc, 'count': con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]}
save('registry_structure.json', db)
save('view_definitions.json', con.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main' AND NOT internal").fetchall())
for table in ['fetch_tasks','raw_batches','canonical_parts','ingestion_runs','endpoint_capabilities']:
    print(table, db.get(table), flush=True)
save('task_summary.json', con.execute('SELECT endpoint,status,error_kind,count(*),sum(rows),max(updated_at) FROM fetch_tasks GROUP BY ALL ORDER BY 1,2').fetchall())
save('canonical_summary.json', con.execute('SELECT endpoint,active,count(*),sum(rows) FROM canonical_parts GROUP BY ALL ORDER BY 1,2').fetchall())
save('raw_summary.json', con.execute('SELECT endpoint,state,count(*),sum(rows) FROM raw_batches GROUP BY ALL ORDER BY 1,2').fetchall())
save('capabilities.json', con.execute('SELECT * FROM endpoint_capabilities').fetchall())
save('recent_runs.json', con.execute('SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT 12').fetchall())
save('task_examples.json', con.execute("SELECT endpoint,status,task,error_kind,error,rows,updated_at FROM fetch_tasks QUALIFY row_number() OVER(PARTITION BY endpoint,status ORDER BY updated_at DESC)<=2").fetchall())
counts=collections.Counter(); sizes=collections.Counter(); layers=collections.Counter(); total=0
with (OUT/'file_manifest.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['path','extension','bytes','mtime_ns','layer','dataset'])
    for base, dirs, files in os.walk(root):
        for name in files:
            p=Path(base)/name;st=p.stat();parts=p.relative_to(root).parts
            w.writerow([str(p),p.suffix.lower(),st.st_size,st.st_mtime_ns,parts[0],parts[1] if len(parts)>2 else ''])
            counts[p.suffix.lower()]+=1;sizes[p.suffix.lower()]+=st.st_size;layers[parts[0]]+=1;total+=1
save('filesystem_summary.json',{'files':total,'extension_counts':counts,'extension_bytes':sizes,'layer_counts':layers})
print('FILES',total,'EXTENSIONS',counts,'LAYERS',layers,flush=True)
defs=ast.parse(Path(r'E:\quant\src\quant\data\schemas\catalog.py').read_text(encoding='utf-8'))
for node in defs.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFINITIONS' for t in node.targets):
        save('catalog_definitions.json',ast.literal_eval(node.value))
con.close()
