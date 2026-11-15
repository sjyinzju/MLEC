"""Rebuild data from the saved raw snapshot and compare actual output bytes."""
import importlib.metadata
import platform
from .common import ROOT,RAW,STANDARD,FEATURES,DATASETS,METADATA,AUDIT,digest,write_json,now


def output_hashes():
    paths=[]
    for folder in [STANDARD,FEATURES,DATASETS]:
        paths.extend(folder.rglob('*.parquet'))
        if folder==DATASETS:paths.extend(folder.rglob('*.json'))
    paths.extend([METADATA/'data_requirements_matrix.parquet',METADATA/'series_catalog.parquet',METADATA/'sources.parquet'])
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths) if p.exists()}


def rebuild_and_compare():
    from .standardize import build
    from .quality import reconcile,completeness,register
    from .features import build_features,all_datasets
    before=output_hashes()
    if not before or not any('/foundation_v3/' in p for p in before):raise ValueError('Build initial datasets before reproducibility verification')
    register()
    from .common import read_json
    inputs=read_json(AUDIT/'source_manifest.json')['offline_input_files']
    env={'python':platform.python_version(),'platform':platform.platform(),'packages':{m:importlib.metadata.version(m) for m in ['pandas','numpy','pyarrow','lxml','openpyxl','xlrd','olefile']}}
    code={p.relative_to(ROOT).as_posix():digest(p) for folder in ['scripts/data_foundation_v3','scripts/macro_pipeline'] for p in sorted((ROOT/folder).glob('*.py'))}
    started=now()
    build();reconcile();completeness();build_features();all_datasets();register()
    after=output_hashes()
    differences=[p for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]
    changed_inputs=[r['path'] for r in inputs if digest(ROOT/r['path'])!=r['sha256']]
    result={'status':'FAIL' if differences or changed_inputs else 'PASS','started_at':started,'completed_at':now(),
        'output_files_compared':len(before),'output_sha256':after,'different_outputs':differences,'changed_inputs':changed_inputs,
        'raw_files_verified':len(inputs),'environment':env,'code_sha256':code,
        'scope':'Offline rebuild from preserved raw evidence with pinned retrieval timestamps; byte-identical Parquet and dataset manifests. Audit run timestamps, request attempts and registry created_at are not deterministic output contracts.',
        'not_claimed':'A Git clone without ignored raw payloads is insufficient; live re-downloads may return revised content. Windows OCR snapshot is retained as diagnostic evidence, not used to certify numeric facts.'}
    write_json(AUDIT/'reproducibility.json',result)
    if differences or changed_inputs:raise AssertionError(result)
    return result
