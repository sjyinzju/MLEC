"""Spawned non-learning workers test the actual shared scheduler and journals."""
from copy import deepcopy
from pathlib import Path
import os
import time
import pytest
from scripts.market_state.framework import DataStore
from scripts.market_state.experiments.config import load_config, candidates
from scripts.market_state.experiments.pipeline import Pipeline
from scripts.market_state.experiments.scheduling import worker_count
from scripts.market_state.experiments.artifacts import atomic_json, read_json, check_files
from scripts.market_state.models.errors import FitFailure


class NonLearningTask:
    def __init__(self, config, data_root, identity):
        self.root = Path(config['output_root'])
        self.failure = config.get('synthetic_failure', False)

    def __call__(self, task, destination, *, save_package):
        if self.failure:
            raise FitFailure('ARTIFICIAL calibrator failure', [dict(component='calibrator', target='0',
                attempt=1, warnings=[], converged=False)])
        # Different durations force out-of-order completion without changing values.
        time.sleep(.01 if task['identity']['fold_id'].endswith('02') else .03)
        value = dict(seed=task['identity']['seed'], fold=task['identity']['fold_id'],
            parameters=task['identity']['parameters'], fit_id=task['fit_id'])
        atomic_json(destination / 'probe.json', value)
        atomic_json(destination / 'process.json', dict(pid=os.getpid()))
        if save_package:
            (destination / 'model_package').mkdir()
            atomic_json(destination / 'model_package/stub.json', dict(purpose='ARTIFICIAL_TEST_ONLY'))
        return dict(predictions=1, mature_rows=1, elapsed_seconds=0., estimator_fit_calls=0,
            calibration_fit_calls=0, diagnostics=[])


def nonlearning_worker(config, data_root, identity):
    # The worker has no estimator or optimizer at all.
    return NonLearningTask(config, data_root, identity)


def pipeline_at(root, workers, **overrides):
    c = load_config('config/experiments/rbf_svm.yaml')
    c.update(purpose='ARTIFICIAL_TEST_ONLY', output_root=str(root), markets=['000985.SH'])
    c.update(overrides)
    c['resources'].update(cpu_workers=workers, minimum_free_gb=0, max_run_gb=1)
    store = DataStore()
    return Pipeline(c, store, run_id='scheduler', resume=True, artificial=True,
        executor=NonLearningTask(c, str(store.root), {}), worker_factory=nonlearning_worker,
        preflight_function=lambda *args: dict(environment={'purpose': 'ARTIFICIAL_TEST_ONLY'}),
        schedule=(['2020-01', '2020-02'], ['2023-01'])).initialize()


def test_spawn_and_serial_task_sets_stable_aggregation_dedup_resume(tmp_path):
    results = []
    for count in [1, 2]:
        pipeline = pipeline_at(tmp_path / str(count), count)
        params = candidates(pipeline.config, 'regression')[0]['parameters']
        items = []
        for fold in ['2020-01', '2020-02', '2020-03', '2020-04']:
            for mode in ['retuned_core', 'fixed_full_params']:
                t = pipeline.task(stage='development', mode=mode, market='000985.SH', task='regression',
                    information='M+Z', fold=fold, parameters=params, seed=3060)
                items.append((t, True))
        records = pipeline.scheduler.map(items)
        if count == 2:
            from scripts.market_state.experiments.scheduling import _worker_task
            fresh = pipeline.task(stage='development', mode='search', market='000985.SH', task='regression',
                information='M', fold='2020-05', parameters=params, seed=3060)
            # Bypass batch dedup deliberately: OS claims must still prevent double work.
            packets = list(pipeline.scheduler.pool.map(_worker_task, [(fresh, False)] * 4))
            failed = [p for p in packets if not p['ok']]
            assert not failed, '\n'.join(p.get('traceback', p['message']) for p in failed)
            assert all(p['record']['files'] == packets[0]['record']['files'] for p in packets)
            assert all(p['record']['attempts'] == 1 for p in packets)
        pipeline.scheduler.close()
        assert len(records) == 8 and len({r['fit_id'] for r in records}) == 4
        assert [r['task_id'] for r in records] == [t['task_id'] for t, _ in items]
        assert len(list((pipeline.root / 'development/fits').glob('*/probe.json'))) == (4 if count == 1 else 5)
        probes = [read_json(pipeline.root / r['artifact'] / 'probe.json') for r in records]
        pids = {read_json(pipeline.root / r['artifact'] / 'process.json')['pid'] for r in records}
        assert (pids == {os.getpid()}) if count == 1 else (os.getpid() not in pids and len(pids) >= 1)
        for r in records: check_files(pipeline.root / r['artifact'], r['files'])
        # Restart with a different worker count, retaining exactly the same identity.
        resumed = pipeline_at(tmp_path / str(count), 1)
        again = resumed.scheduler.map(items)
        assert [r['files'] for r in again] == [r['files'] for r in records]
        results.append(([(r['task_id'], r['fit_id']) for r in records], probes))
    assert results[0] == results[1]


def test_interrupted_running_task_restarts_once_and_failed_io_is_preserved(tmp_path):
    pipeline = pipeline_at(tmp_path, 2)
    params = candidates(pipeline.config, 'classification')[0]['parameters']
    task = pipeline.task(stage='development', mode='search', market='000985.SH', task='classification',
        information='M', fold='2020-01', parameters=params, seed=3060)
    pipeline.journal.record(task, status='RUNNING', attempts=1, attempt_history=[])
    try:
        result = pipeline.scheduler.map([(task, False)])[0]
    finally:
        pipeline.scheduler.close()
    assert result['status'] == 'SUCCEEDED' and result['attempts'] == 2
    assert result['interrupted_fit_calls_unknown']
    assert result['estimator_fit_calls'] == 0
    def alias(mode):
        return pipeline.task(stage='development', mode=mode, market='000985.SH', task='classification',
            information='M', fold='2020-01', parameters=params, seed=3060)
    reused = pipeline.monthly(alias('fixed_full_params'))
    assert reused['reused'] and reused['attempts'] == 2
    from scripts.market_state.experiments.reports import retry_counts
    assert retry_counts(reused)['task_retries'] == 1
    artifact = pipeline.root / reused['artifact']
    missing = artifact.with_name(artifact.name + '-missing')
    assert artifact.resolve().is_relative_to(pipeline.root.resolve()) and missing.resolve().is_relative_to(pipeline.root.resolve())
    artifact.rename(missing)
    with pytest.raises(RuntimeError, match='artifact missing'):
        pipeline.monthly(alias('retuned_core'))


def test_resource_default_is_bounded_and_override_is_explicit(monkeypatch):
    from scripts.market_state.experiments import scheduling
    c = load_config('config/experiments/rbf_svm.yaml')
    monkeypatch.setattr(scheduling.os, 'cpu_count', lambda: 32)
    monkeypatch.setattr(scheduling, 'available_memory_gb', lambda: 6)
    assert worker_count(c) == 2
    c['resources']['cpu_workers'] = 5
    assert worker_count(c) == 5


def test_physical_failure_budget_cannot_restart_through_an_analysis_alias(tmp_path):
    pipeline = pipeline_at(tmp_path, 2, synthetic_failure=True)
    params = candidates(pipeline.config, 'classification')[0]['parameters']
    def task(mode):
        return pipeline.task(stage='development', mode=mode, market='000985.SH', task='classification',
            information='M', fold='2020-01', parameters=params, seed=3060)
    try:
        assert pipeline.scheduler.map([(task('search'), False)], allow_fit_failure=True) == [None]
        assert pipeline.scheduler.map([(task('fixed_full_params'), False)], allow_fit_failure=True) == [None]
    finally:
        pipeline.scheduler.close()
    a = read_json(pipeline.journal.path(task('search')))
    b = read_json(pipeline.journal.path(task('fixed_full_params')))
    assert a['attempts'] == b['attempts'] == 2
    assert a['calibration_fit_calls'] == b['calibration_fit_calls'] == 2
    assert a['attempt_history'] == b['attempt_history']
    assert a['estimator_fit_calls'] == b['estimator_fit_calls'] == 0


@pytest.mark.parametrize('error,kind,status', [
    (OSError, 'IO', 'FAILED'), (MemoryError, 'RESOURCE', 'FAILED'),
    (ValueError, 'CONTRACT', 'FAILED'), (KeyboardInterrupt, 'USER_INTERRUPTION', 'INTERRUPTED')])
def test_failed_and_interrupted_attempts_have_time_and_recoverable_history(tmp_path, error, kind, status):
    pipeline = pipeline_at(tmp_path, 1)
    params = candidates(pipeline.config, 'classification')[0]['parameters']
    task = pipeline.task(stage='development', mode='search', market='000985.SH', task='classification',
        information='M', fold='2020-01', parameters=params, seed=3060)
    original = pipeline.executor
    def fail(*args, **kwargs):
        raise error('ARTIFICIAL failure')
    pipeline.executor = fail
    with pytest.raises(error): pipeline.monthly(task)
    record = read_json(pipeline.journal.path(task))
    assert record['failure_kind'] == kind and record['status'] == status
    assert record['elapsed_seconds'] > 0 and len(record['attempt_history']) == 1
    assert record['estimator_fit_calls'] == 0
    if kind != 'CONTRACT':
        pipeline.executor = original
        done = pipeline.monthly(task)
        assert done['status'] == 'SUCCEEDED' and done['attempts'] == 2
        assert len(done['attempt_history']) == 2
        alias = dict(task, task_id='alias')
        pipeline.monthly(alias)
        assert pipeline.journal.artifact_bytes == done['artifact_bytes']


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows access-denied rename semantics')
def test_staging_retries_transient_windows_access_denial_without_rewriting(tmp_path, monkeypatch):
    from scripts.market_state.experiments import artifacts
    original = artifacts.os.replace
    calls = []

    def replace(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            error = PermissionError(13, 'Windows temporarily held the staged directory')
            error.winerror = 5
            raise error
        return original(source, destination)

    monkeypatch.setattr(artifacts.os, 'replace', replace)
    target = tmp_path / 'committed'
    with artifacts.staging(target) as staged:
        (staged / 'predictions.parquet').write_bytes(b'one staged result')
    assert len(calls) == 2 and calls[0] == calls[1]
    assert (target / 'predictions.parquet').read_bytes() == b'one staged result'
