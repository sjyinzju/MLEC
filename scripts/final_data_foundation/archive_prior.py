"""Preserve original tracked registry/report bytes before authoritative replacement."""
import subprocess
from .common import *


def archive(paths):
    baseline=read(AUDIT/'integrity/baseline.json');ledger=[]
    for path in paths:
        if path not in baseline['files']:continue
        expected=baseline['files'][path]['sha256'];destination=ROOT/'data/archive/data-foundation-v3'/path
        if destination.exists():assert sha(destination)==expected
        else:
            original=ROOT/path
            if original.exists() and sha(original)==expected:payload=original.read_bytes()
            else:
                payload=subprocess.check_output(['git','show',baseline['git_head']+':'+path],cwd=ROOT)
                if hashlib.sha256(payload).hexdigest()!=expected and Path(path).suffix in ['.json','.md']:
                    # Git stores LF; original Windows checkout may use CRLF.
                    # Accept only the exact initial baseline digest.
                    payload=payload.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            assert hashlib.sha256(payload).hexdigest()==expected
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(payload)
        ledger.append({'original_path':path,'archived_path':destination.relative_to(ROOT).as_posix(),'sha256':expected})
    p=AUDIT/'integrity/prior_authorities_archived.json';old=read(p) if p.exists() else []
    write(p,list({r['original_path']:r for r in old+ledger}.values()))


if __name__=='__main__':
    archive(['data/metadata/data_lineage.parquet','data/metadata/dataset_registry.json','data/metadata/schema_registry.json','reports/data_quality/final_data_acceptance.md'])
