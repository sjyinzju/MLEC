"""Pinned research snapshot, content provenance and explicit release versions."""
import hashlib
import subprocess
from .common import *

RELEASE=OUT/'release'

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def begin():
    p=RELEASE/'input_snapshot.json'
    if p.exists():return json.loads(p.read_text(encoding='utf8'))
    paths=list((OUT/'sources').rglob('*.parquet'))
    paths += [p for name in ['stock_daily_observations','stock_daily_basic_observations','stock_adjustment_observations','stock_trading_status'] for p in (BASE/name).glob('*.parquet')]
    paths += [BASE/'stock_master_history.parquet',BASE/'stock_code_changes.parquet',BASE/'market_data_quality.parquet',ROOT/'data/standardized/macro/v4/macro_facts.parquet']
    baseline={'snapshot_id':'mlec-formal-20261113','cutoff':'2026-11-13','asof_time':'2026-11-13T18:00:00+08:00',
        'recorded_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        'protocol_sha256':file_hash(ROOT/'docs/MLEC_research_protocol.md'),
        'inputs':{p.relative_to(ROOT).as_posix():{'sha256':file_hash(p),'bytes':p.stat().st_size} for p in sorted(set(paths)) if p.exists()},
        'external_read_only':{'path':'E:/QuantData/quant.duckdb','size':Path('E:/QuantData/quant.duckdb').stat().st_size,'mtime_ns':Path('E:/QuantData/quant.duckdb').stat().st_mtime_ns},
        'dictionary_before':json.loads((OUT/'state_dictionary/dictionary.json').read_text(encoding='utf8'))['label_version']}
    write(p,baseline);return baseline

def cutoff():
    p=RELEASE/'input_snapshot.json'
    return pd.Timestamp(json.loads(p.read_text(encoding='utf8'))['cutoff']) if p.exists() else pd.Timestamp('2026-11-13')

def code_hash():
    return digest({p.name:file_hash(p) for p in sorted((ROOT/'scripts/market_state').glob('*.py'))})

def product_hashes():
    paths=[p for p in OUT.rglob('*.parquet') if not {'cache','sources','release'}&set(p.relative_to(OUT).parts)]
    paths += [OUT/p for p in ['feature_sets.json','missing_policy.json','research_dependencies.json','data_task_config.json',
        'market_universe.json','dataset_manifest.json','macro/specifications.json','state_dictionary/dictionary.json','state_dictionary/dictionary.joblib']]
    return {p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths) if p.exists()}

def verify_rebuild():
    import os
    before=product_hashes();log=REPORT/'reproducible_build.log'
    with log.open('w',encoding='utf8') as f:
        subprocess.run([sys.executable,'-u','-m','scripts.market_state.run','build','--reuse-dictionary'],cwd=ROOT,
            stdout=f,stderr=subprocess.STDOUT,check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    after=product_hashes();changed=[p for p in set(before)|set(after) if before.get(p)!=after.get(p)]
    write(REPORT/'reproducibility.json',dict(passed=not changed,products_compared=len(before),changed=changed,
        current_product_hashes=after,cache_parent_dependency='content+calendar+identity+code+previous-year partition'))
    if changed:raise ValueError('Rebuild changed products: '+str(changed))
    return len(before)

def seal():
    spec=json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    acceptance=json.loads((REPORT/'acceptance_validation.json').read_text(encoding='utf8'))
    batch=json.loads((REPORT/'batch_preflight.json').read_text(encoding='utf8'))
    reproduction=json.loads((REPORT/'reproducibility.json').read_text(encoding='utf8'))
    tests=json.loads((REPORT/'test_exit.json').read_text(encoding='utf8'))
    assert acceptance['passed'] and batch['failed']==0 and reproduction['passed'] and tests['exit_code']==0
    assert acceptance['target_version']==batch['target_version']==spec['target_version']
    assert acceptance['feature_version']==batch['feature_version']==spec['feature_version']
    assert acceptance['calculation_code_hash']==batch['calculation_code_hash']==code_hash(),'Code changed after acceptance'
    policy=json.loads((OUT/'missing_policy.json').read_text(encoding='utf8'))
    audit=read('release/macro_period_audit');formal={r['series_id'] for r in policy['series'] if r['formal']}
    assert not (audit.series_id.isin(formal)&audit.status.eq('SOURCE_GAP')).any(),'Unadjudicated formal macro period'
    current=product_hashes()
    assert reproduction['current_product_hashes']==current,'Products changed after reproducibility verification'
    baseline=begin();additions={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted((OUT/'sources').rglob('*')) if p.is_file()}
    # Validate actual raw inputs still match the recorded snapshot. Targeted
    # admissions are separately bound above, never silently mutate base inputs.
    for relative,value in baseline['inputs'].items():
        assert file_hash(ROOT/relative)==value['sha256'],'Unrecorded original input update: '+relative
    external=baseline['external_read_only'];ext=Path(external['path']).stat()
    assert ext.st_size==external['size'] and ext.st_mtime_ns==external['mtime_ns'],'External registry changed during pinned acceptance'
    payload=dict(snapshot_id=baseline['snapshot_id'],cutoff=baseline['cutoff'],products=current,
        original_input_hashes={k:v['sha256'] for k,v in baseline['inputs'].items()},admissions=additions,
        code_hash=code_hash(),dictionary_version=spec['label_version'],target_version=spec['target_version'],
        feature_version=spec['feature_version'],missing_policy_version=spec['missing_policy_version'])
    payload.update(data_version=digest(payload)[:24],status='SEALED_READY_FOR_MODEL_SELECTION',
        supervised_models_run=0,acceptance='reports/market_state/completion_report.md',
        permissible_missing='Fixed machine-readable policy; no unadjudicated formal series gaps',
        external_registry_unchanged=True)
    write(RELEASE/'seal.json',payload)
    from .report import report
    report()
    print('SEALED',payload['data_version'],flush=True)
    return payload

def assert_sealed_products(*,require=True):
    p=RELEASE/'seal.json'
    if not p.exists():
        if require:raise RuntimeError('Formal seal required; use explicit analysis for draft inspection')
        return None
    record=json.loads(p.read_text(encoding='utf8'))
    if record['status']!='SEALED_READY_FOR_MODEL_SELECTION':raise RuntimeError('Release is not accepted')
    for relative,expected in record['products'].items():
        path=ROOT/relative
        if not path.exists() or file_hash(path)!=expected:raise RuntimeError('Formal sealed data changed; rebuild/accept/reseal before reading: '+relative)
    return record['data_version']
