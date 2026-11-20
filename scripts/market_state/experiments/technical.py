"""Explicit, small real-solver acceptance. Temporary fits never enter research."""
from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import time
import numpy as np
import pandas as pd
from ..common import ROOT, digest
from ..framework import DataStore, load_dataset
from ..interface_acceptance import assert_interface_accepted
from ..model_contract import fit_inputs, transform_inputs, prediction_context
from ..models.elastic_net import ElasticNetAdapter
from ..preprocessing import input_diagnostics
from ..release import file_hash
from .artifacts import TaskJournal, atomic_json, read_json, native_path
from .config import load_config
from .pipeline import Pipeline
from .runtime import MonthlyExecutor, versions, environment, experiment_code_hash
from .scheduling import TaskRunner, TaskScheduler, worker_count, process_usage


class _TechnicalRunner(TaskRunner):
    # Use the same identity builder, leases, retry/commit path and scheduler as
    # formal execution. This entry has no selection, locking or C-stage call.
    task = Pipeline.task

    def __init__(self, config, store, root, workers):
        self.config = deepcopy(config)
        self.config['purpose'] = 'SMOKE_ONLY'
        self.config['resources']['cpu_workers'] = workers
        self.config['resources']['threads_per_task'] = 1
        self.config['resources']['minimum_free_gb'] = 0
        self.store, self.root = store, native_path(root)
        self.root.mkdir(parents=True)
        self.identity = versions(self.config, store)
        self.artificial = False
        self.journal = TaskJournal(self.root, resume=True, max_attempts=self.config['policy']['task_attempts'])
        self.executor = MonthlyExecutor(self.config, store, self.identity)
        self.scheduler = TaskScheduler(self)


def scenarios(quick):
    cohorts = [('000905.SH', '2020-01')] if quick else [
        ('000905.SH', '2020-01'), ('000985.SH', '2020-01'), ('000852.SH', '2021-10')]
    rows = []
    for market, fold in cohorts:
        for task in ['classification', 'regression']:
            values = ([.0001] if quick else [.0001, 1e4]) if task == 'classification' else ([.01] if quick else [1e-5, 10.])
            for info in ['M', 'M+Z']:
                for value in values:
                    parameters = dict(l1_ratio=.05 if task == 'classification' or value < 10. else .95, tol=1e-4, max_iter=10000)
                    parameters['C' if task == 'classification' else 'alpha'] = value
                    rows.append(dict(market=market, fold=fold, task=task, information=info, parameters=parameters))
    if not quick:
        rows.extend(dict(market='000985.SH', fold='2020-01', task='regression', information=info,
            parameters=dict(alpha=5.945570708544395e-5, l1_ratio=1., tol=1e-4, max_iter=10000))
            for info in ['M', 'M+Z'])
        rows.append(dict(market='000852.SH', fold='2021-10', task='regression', information='M+Z',
            parameters=dict(alpha=1.5615230060004964e-5, l1_ratio=.95, tol=1e-4, max_iter=10000)))
        rows.append(dict(market='000300.SH', fold='2020-10', task='regression', information='M+Z',
            parameters=dict(alpha=5.945570708544395e-5, l1_ratio=1., tol=1e-4, max_iter=10000)))
    return rows


def _batch(config, store, root, workers, design):
    runner = _TechnicalRunner(config, store, root, workers)
    items = [(runner.task(stage='development', mode='SMOKE_ONLY', seed=3060, **row), True) for row in design]
    before = process_usage()
    start = time.perf_counter()
    try:
        # Separate cold process/import cost from already-running pool throughput.
        first = runner.scheduler.map(items[:4])
        cold_seconds = time.perf_counter() - start
        remaining = runner.scheduler.map(items[4:]) if len(items) > 4 else []
        elapsed = time.perf_counter() - start
        records = first + remaining
    finally:
        runner.scheduler.close()
    predictions, losses, checks = [], [], []
    for (task, _), record in zip(items, records):
        directory = root / record['artifact']
        model = ElasticNetAdapter.load(directory / 'model_package')
        train, pre, target, pred, x, xp = runner.executor.matrices(task)
        if task['identity']['task'] == 'classification' and task['identity']['parameters']['C'] == .0001:
            assert record['estimator_fit_calls'] == 0
            assert record['diagnostics'][0]['solver'] == 'certified_zero_slopes'
            expected = train.y.future_state_id.value_counts(normalize=True).reindex(target.schema_['class_ids'], fill_value=0)
            np.testing.assert_allclose(model.estimators_[0].predict_proba(x),
                np.tile(expected[expected.gt(0)], (len(x), 1)), rtol=0, atol=3e-15)
        ctx = prediction_context(pred, pre, target, model_id='elastic_net', model_version=model.model_version_, input_matrix=xp)
        saved = pd.read_parquet(directory / 'predictions.parquet')
        pd.testing.assert_frame_equal(model.predict(xp, ctx), saved, check_exact=True)
        predictions.append(saved)
        losses.append(pd.read_parquet(directory / 'losses.parquet'))
        checks.append(dict(**task['identity'], model_version=model.model_version_,
            input=read_json(directory / 'context.json')['input_diagnostics'],
            diagnostics=record['diagnostics'], save_load_predict_exact=True,
            estimator_fit_calls=record['estimator_fit_calls'], elapsed_seconds=record['elapsed_seconds']))
    # Resume the exact tasks, including process-count changes: no additional fits.
    mtime = {str(p): p.stat().st_mtime_ns for p in root.glob('development/fits/*/artifact.json')}
    runner.scheduler.workers = 1
    again = runner.scheduler.map(items)
    assert [r['files'] for r in again] == [r['files'] for r in records]
    assert mtime == {str(p): p.stat().st_mtime_ns for p in root.glob('development/fits/*/artifact.json')}
    usage = {}
    for r in records:
        u = r['process_usage']; pid = str(u['pid'])
        previous = usage.get(pid, {})
        usage[pid] = dict(peak_rss_bytes=max(previous.get('peak_rss_bytes', 0), u['peak_rss_bytes'] or 0),
            cpu_seconds=max(previous.get('cpu_seconds', 0.), u['cpu_seconds']))
    after = process_usage()
    summary = dict(workers=workers, threads_per_task=1, elapsed_seconds=elapsed,
        cold_first_four_seconds=cold_seconds, remaining_warm_pool_seconds=elapsed-cold_seconds,
        coordinator_cpu_seconds=after['cpu_seconds']-before['cpu_seconds'],
        coordinator_peak_rss_bytes=after['peak_rss_bytes'], per_solver_process=usage,
        memory_measurement='OS per-process high-water RSS; not summed as a simultaneous system peak',
        successful_monthly_tasks=len(records), estimator_fit_calls=sum(r['estimator_fit_calls'] for r in records),
        cache_hits_by_process={pid: max((r['cache_statistics']['matrix_hits'] for r in records if str(r['process_usage']['pid']) == pid), default=0) for pid in usage},
        resume_reused_all_without_fit=True, checks=checks)
    return summary, predictions, losses


def technical_check(*, execute=False, quick=False, destination=None, data_root=None, cpu_workers=None):
    if not execute:
        print('TECHNICAL_ONLY planned; fits=0 without --execute; no formal B/C stage')
        return
    config = load_config()
    config['data_root'] = str(data_root or ROOT / config['data_root'])
    store = DataStore(config['data_root'])
    assert_interface_accepted(data_root=store.root)
    tests = read_json(ROOT / 'reports/market_state/model_io/test_results.json')
    if tests.get('experiment_code_hash') != experiment_code_hash() or tests.get('exit_code') != 0:
        raise RuntimeError('Technical acceptance requires current full non-training pytest')
    env = environment()
    workers = cpu_workers or min(4, worker_count(config))
    if workers < 2:
        raise RuntimeError('At least two workers needed for real serial/process comparison; set --cpu-workers explicitly')
    destination = Path(destination or ROOT / ('reports/model_build/elastic_net/quick_technical.json' if quick else 'reports/model_build/elastic_net/optimization_20261119/real_technical.json'))
    result = dict(purpose='SMOKE_ONLY', research_evidence=False, formal_BC_started=False,
        quick=quick, environment=env, cpu_logical=os.cpu_count(), available_workers=worker_count(config),
        original_seal_sha256=file_hash(store.root / 'release/seal.json'), code=experiment_code_hash(),
        design=scenarios(quick), numerical_tolerances=dict(rtol=1e-10, classification_atol=1e-12, regression_atol=1e-24))
    try:
        scans = []
        for market in config['markets']:
            for fold in ['2020-01', '2022-12']:
                d = load_dataset(market_id=market, fold_id=fold, task='classification', information_set='M+Z', role='train', store=store)
                pre = fit_inputs(d); x = transform_inputs(pre, d)
                probabilities = [c for c in x if c.startswith('current_state_prob_')]
                assert (x[probabilities].to_numpy() >= 0).all() and (x[probabilities].to_numpy() <= 1).all()
                scans.append(dict(market=market, fold=fold, **input_diagnostics(x)))
        result['input_scans'] = scans
        # Keep the extended Windows prefix for cleanup too, so a failed fit is
        # not masked by MAX_PATH errors while removing its temporary model.
        with tempfile.TemporaryDirectory(prefix='mlec-technical-', dir=native_path(tempfile.gettempdir())) as temp:
            root = Path(temp)
            serial, a, al = _batch(config, store, root/'serial', 1, scenarios(quick))
            parallel, b, bl = _batch(config, store, root/'parallel', workers, scenarios(quick))
            differences = []
            for design, left, right, ls, rs in zip(scenarios(quick), a, b, al, bl):
                columns = [c for c in left if c.startswith('predicted_')]
                atol = 1e-12 if design['task'] == 'classification' else 1e-24
                np.testing.assert_allclose(left[columns], right[columns], rtol=1e-10, atol=atol)
                np.testing.assert_allclose(ls.loss, rs.loss, rtol=1e-10, atol=1e-12)
                differences.append(float(np.abs(left[columns].to_numpy()-right[columns].to_numpy()).max(initial=0)))
            def rankings(frames):
                groups = {}
                for d, f in zip(scenarios(quick), frames):
                    key = '|'.join(d[k] for k in ['market', 'fold', 'task', 'information'])
                    groups.setdefault(key, []).append((float(f.loss.mean()), digest(d['parameters'])))
                return {k:[v[1] for v in sorted(rows)] for k,rows in groups.items()}
            assert rankings(al) == rankings(bl)
            result.update(serial=serial, parallel=parallel, prediction_max_differences=differences,
                candidate_ranking_equal=True, ranking_hash=digest(rankings(al)),
                total_speedup=serial['elapsed_seconds']/parallel['elapsed_seconds'],
                warm_pool_speedup=serial['remaining_warm_pool_seconds']/parallel['remaining_warm_pool_seconds'] if not quick else None,
                status='PASSED', predictions_retained=False, model_weights_retained=False)
    except BaseException as error:
        original = error
        while not hasattr(original, 'diagnostics') and original.__context__ is not None:
            original = original.__context__
        result.update(status='FAILED', error=type(original).__name__+': '+str(original), diagnostics=getattr(original, 'diagnostics', []))
        if original is not error:
            result['secondary_error'] = type(error).__name__+': '+str(error)
        atomic_json(destination, result)
        raise
    atomic_json(destination, result)
    print('TECHNICAL_ONLY PASSED; serial/parallel predictions, scoring, ranking, package load and resume verified; no formal B/C')
    return result


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--cpu-workers', type=int)
    technical_check(**vars(parser.parse_args()))
