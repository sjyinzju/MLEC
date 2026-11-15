"""Idempotent inventory and verified, non-destructive submission snapshot."""
import shutil
import subprocess
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from .common import ROOT, digest, read_json, write_json, save_frame

AUDIT = ROOT / 'audit/framework'

def freeze():
    AUDIT.mkdir(parents=True, exist_ok=True)
    if (AUDIT / 'baseline.json').exists():
        return read_json(AUDIT / 'baseline.json')
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0'))
    rows = []
    for folder in ['data/research_v2', 'config/research_v2', 'scripts/research_v2', 'audit/research_v2', 'reports/research_v2', 'data_raw', 'deliverables']:
        for p in sorted((ROOT / folder).rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts: continue
            rel = p.relative_to(ROOT).as_posix()
            row = dict(path=rel, bytes=p.stat().st_size, sha256=digest(p), tracked=rel in tracked)
            if p.suffix == '.parquet':
                q = pq.ParquetFile(p); row.update(rows=q.metadata.num_rows, schema=str(q.schema_arrow))
            rows.append(row)
    baseline = {'git_head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip(),
                'git_status': subprocess.check_output(['git','status','--porcelain'], cwd=ROOT).decode(),
                'root': str(ROOT), 'files': rows}
    write_json(AUDIT / 'baseline.json', baseline)
    return baseline

def snapshot():
    baseline = freeze(); moves = []
    dest = ROOT / 'data/raw/macro/original_submissions/v1'
    for r in baseline['files']:
        if not r['path'].startswith(('data_raw/', 'deliverables/')): continue
        src = ROOT / r['path']; dst = dest / r['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists(): shutil.copy2(src, dst)
        if digest(dst) != r['sha256']: raise ValueError(f'Snapshot changed: {dst}')
        moves.append({'old_path':r['path'], 'canonical_snapshot':dst.relative_to(ROOT).as_posix(),
                      'sha256':r['sha256'], 'action':'verified_copy; legacy retained until reference audit' if src.exists() else 'verified_copy_then_removed_legacy_file; recover_from_canonical_snapshot'})
    write_json(AUDIT / 'migration.json', moves)
    return moves

def verify_market():
    checks = []
    for r in read_json(AUDIT / 'baseline.json')['files']:
        if r['path'].startswith(('data/research_v2/', 'config/research_v2/', 'audit/research_v2/')):
            checks.append({'path':r['path'], 'unchanged':digest(ROOT/r['path']) == r['sha256']})
    write_json(AUDIT / 'market_integrity.json', checks)
    if not all(r['unchanged'] for r in checks): raise ValueError('Frozen market artifacts changed')
    return len(checks)

def finalize_migration():
    """Remove only individually verified legacy data copies, never directories."""
    entries=read_json(AUDIT/'migration.json')
    for r in entries:
        p=(ROOT/r['old_path']).resolve(); target=(ROOT/r['canonical_snapshot']).resolve()
        if not p.is_relative_to(ROOT) or not target.is_relative_to(ROOT/'data/raw/macro'):
            raise ValueError('Migration path escapes project')
        if p.suffix.lower() not in ['.csv','.parquet','.json']:continue
        if digest(target)!=r['sha256']:raise ValueError('Snapshot differs')
        if p.exists():
            if digest(p)!=r['sha256']:raise ValueError('Legacy source changed since audit')
            p.unlink()
        r['action']='verified_copy_then_removed_legacy_file; recover_from_canonical_snapshot'
    write_json(AUDIT/'migration.json',entries)

def archive_packages():
    records=[];folder=ROOT/'data/raw/macro/original_submissions/packages';folder.mkdir(parents=True,exist_ok=True)
    for name in ['data_raw.zip','deliverables.zip']:
        src=(ROOT/name).resolve();dst=(folder/name).resolve()
        assert src.parent==ROOT and dst.is_relative_to(ROOT/'data/raw/macro')
        if src.exists():
            sha=digest(src)
            if not dst.exists():shutil.copy2(src,dst)
            assert digest(dst)==sha
            src.unlink()
        records.append({'old_path':name,'archive':dst.relative_to(ROOT).as_posix(),'sha256':digest(dst),'action':'verified_copy_then_removed_original; recover_from_archive'})
    write_json(AUDIT/'package_migration.json',records)

if __name__ == '__main__':
    snapshot(); print('Frozen market artifacts verified:', verify_market())
