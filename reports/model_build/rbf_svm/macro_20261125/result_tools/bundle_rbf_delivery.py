"""Build a local, hash-verified delivery ZIP from a finished RBF run."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import pandas as pd

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    run=args.run.resolve()
    base=run.parents[1]
    delivery=run/'delivery'
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf8'))
    chain=json.loads((base/'execution_chain.json').read_text(encoding='utf-8-sig'))
    if manifest['state']!='EXPERIMENT_COMPLETE' or chain[-1].get('exit_code')!=0:
        raise ValueError('The official pipeline must finish before packaging')
    tasks=pd.read_parquet(run/'tasks.parquet',columns=['stage','status','fit_id','estimator_fit_calls','calibration_fit_calls','artifact_bytes'])
    phases={}
    for stage, rows in tasks.groupby('stage'):
        physical=rows[rows.status.eq('SUCCEEDED')].groupby('fit_id',sort=False)[['estimator_fit_calls','calibration_fit_calls','artifact_bytes']].max()
        phases[stage] = dict(logical_tasks=len(rows), physical_successes=len(physical), logical_states=rows.status.value_counts().to_dict(),
            counts={k:int(v) for k,v in physical.sum().items()})
    (delivery/'executed_tasks_summary.json').write_text(json.dumps(phases,indent=2),encoding='utf8')
    sources={}
    def collect(path, name):
        sources[name]=path
    for name in ['manifest.json','config.resolved.yaml','selection.lock.json','preflight.json','environment.json','report.md']:
        collect(run/name,name)
    collect(run/'development/report.md','development/report.md')
    collect(run/'logs/failures.json','logs/task_failures.json')
    for phase, dest in [('development','development'),('test','test')]:
        prefix=run/'development' if phase=='development' else run
        for folder in ['tables','figures']:
            for path in (prefix/folder).glob('*'):
                if path.is_file() and path.name!='macro_groups.png':
                    collect(path,f'{dest}/{folder}/{path.name}')
        phase_dir=run/phase
        collect(phase_dir/'report_manifest.json',dest+'/report_manifest.json')
        for subpath in ['metrics/rbf_probability_evidence.parquet','metrics/selected_scores.parquet',
            'losses/seed_averaged_differences.parquet']:
            collect(phase_dir/subpath,dest+'/'+subpath)
    for path in (run/'development/rbf_diagnostics').glob('*'):
        collect(path,'development/diagnostics/'+path.name)
    for path in (base/'acceptance_evidence').glob('*'):
        collect(path,'acceptance/'+path.name)
    for path in (base/'logs').glob('*.log'):
        collect(path,'logs/'+path.name)
    for name in ['historical_provenance.json','recovered_test_asset.json','commands.json','execution_chain.json',
        'executed_source_4493be5153575e180993d287.zip.sha256','export_rbf_report.py','render_rbf_delivery.py','bundle_rbf_delivery.py']:
        collect(base/name,'reproduction/'+name)
    for path in delivery.glob('*'):
        if path.is_file() and path.suffix not in ['.zip','.sha256'] and path.name not in ['bundle_inventory.json','delivery_index.json']:
            collect(path,'delivery/'+path.name)
    for name,path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(name)
    inventory={name:dict(sha256=sha(path),bytes=path.stat().st_size) for name,path in sorted(sources.items())}
    inventory_path=delivery/'bundle_inventory.json'
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf8')
    package=delivery/('rbf_results_'+manifest['run_id']+'.zip')
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for name, path in sources.items():
            z.write(path,name)
        z.write(inventory_path,inventory_path.name)
    with zipfile.ZipFile(package) as z:
        assert len(z.namelist())==len(inventory)+1
        for name, item in inventory.items():
            with z.open(name) as stream:
                assert hashlib.file_digest(stream,'sha256').hexdigest()==item['sha256'],name
    checksum=sha(package)
    package.with_suffix('.zip.sha256').write_text(checksum+'  '+package.name+'\n',encoding='ascii')
    print(package,package.stat().st_size,checksum,flush=True)

if __name__=='__main__':
    main()
