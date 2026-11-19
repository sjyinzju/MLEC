"""Read original export, never execute its code or refit a historical model."""
from pathlib import Path
import sys, subprocess, zipfile, json, hashlib, io
import numpy as np
import pandas as pd

out = Path(__file__).resolve().parent
src = Path(sys.argv[1])
ref = 'origin/archive/elastic-net-60c8639d-20261119'
prefix = 'research_archives/elastic_net/60c8639de8935d891b0e79d1/'
sha = lambda b: hashlib.sha256(b).hexdigest()
audit_bytes = subprocess.check_output(['git', 'show', ref+':'+prefix+'MLEC_ElasticNet_audit_evidence.json'])
audit = json.loads(audit_bytes)  # Entire JSON parsed, every section content-hashed below.
p = 'results/elastic_net/60c8639de8935d891b0e79d1/'
record = dict(run_id=audit['run_id'], archive_before='047f76de38d726f6e2fda86b53a0fd71a2ba65f1',
    archive_after=subprocess.check_output(['git', 'rev-parse', ref]).decode().strip(),
    zip_name=src.name, zip_bytes=src.stat().st_size, zip_sha256=sha(src.read_bytes()),
    audit_json_sha256=sha(audit_bytes), audit_sections={k:dict(type=type(v).__name__,
        entries=len(v) if isinstance(v, (list, dict)) else None,
        content_sha256=sha(json.dumps(v, sort_keys=True).encode())) for k,v in audit.items()})
with zipfile.ZipFile(src) as z:
    export = json.loads(z.read(p+'EXPORT_MANIFEST.json'))
    record['export_checks'] = [dict(**f, verified=(len(z.read(f['path'])) == f['bytes'] and sha(z.read(f['path'])) == f['sha256'])) for f in export['files']]
    assert len(record['export_checks']) == 65 and all(f['verified'] for f in record['export_checks'])
    m = json.loads(z.read(p+'manifest.json'))
    lock = json.loads(z.read(p+'selection.lock.json'))
    search = json.loads(z.read(p+'development/selection/search.json'))
    record.update(suite=m['suite'], state=m['state'], versions=m['versions'],
        lock_hash_verified=sha(z.read(p+'selection.lock.json')) == m['lock_hash'],
        search_hash_verified=sha(z.read(p+'development/selection/search.json')) == lock['development_evidence']['search_hash'])
    record['search_summary'] = {t:dict(candidates=sum(len(g['coarse']) for g in search.values() if g['task']==t),
        invalid=sum(not c['valid'] for g in search.values() if g['task']==t for c in g['coarse'])) for t in ['classification', 'regression']}
    record['regression_winners'] = {k:g['winner']['parameters'] for k,g in search.items() if g['task']=='regression'}
    quality = pd.concat([pd.read_csv(io.BytesIO(z.read(p+t))) for t in ['development/tables/runtime_quality.csv', 'tables/runtime_quality.csv']], ignore_index=True)
    failed = quality[quality.status.eq('FAILED')]
    record['runtime'] = dict(rows=len(quality), negative_retry_rows=int(quality.retries.lt(0).sum()),
        failed_regression_rows=int((failed.task=='regression').sum()), failed_elapsed_missing=int(failed.elapsed_seconds.isna().sum()),
        zero_elapsed=int(failed.elapsed_seconds.eq(0).sum()))
    for stage,path in [('development','development/metrics/selected_scores.parquet'), ('test','test/metrics/selected_scores.parquet')]:
        scores = pd.read_parquet(io.BytesIO(z.read(p+path)))
        f = scores[scores.task.eq('classification')]
        v = f[['predicted_state_prob_'+str(c) for c in [0,1,2]]].to_numpy()
        y = f.future_state_id.to_numpy(int)
        ll = -np.log(np.maximum(v[np.arange(len(v)), y], 1e-15))
        brier = (np.square(v-np.eye(3)[y])).sum(axis=1)
        record[stage+'_prediction_arithmetic'] = dict(rows=len(f), logloss_maxdiff=float(abs(ll-f.log_loss).max()),
            brier_maxdiff=float(abs(brier-f.brier).max()), argmax_mismatch=int((v.argmax(axis=1)!=f.predicted_state_id).sum()))
    notes = z.read('HOW_TO_APPLY.txt')
    try: notes = notes.decode('utf8')
    except UnicodeDecodeError: notes = notes.decode('gb18030')
    record['external_runtime_notes'] = notes
    record['missing_evidence'] = {n:'Absent from original export and searched local project; not regenerated' for n in [
        'fits/: per-fit predictions, coefficients and model packages', 'tasks.parquet and per-task diagnostics',
        '_parallel/: source, queues and worker logs', 'in-memory hash shim source and serial-parallel validation record']}
    record['archive_prior_files_untouched'] = True
(out/'old_run_evidence.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps({k:v for k,v in record.items() if k in ['zip_bytes','zip_sha256','search_summary','runtime','development_prediction_arithmetic','test_prediction_arithmetic']}, indent=2))
