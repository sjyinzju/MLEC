"""One execution path for serial/process scheduling and identity-checked fit reuse."""
from pathlib import Path
import shutil
import os
import multiprocessing
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from ..models.errors import FitFailure, fit_counts, ResourceFailure
from .artifacts import TaskJournal, read_json, staging, file_manifest, check_files, atomic_json, exclusive_run


def available_memory_gb():
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ['total', 'available', 'page_total', 'page_available',
                    'virtual_total', 'virtual_available', 'extended']]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.available / 1024 ** 3
    else:
        try:
            return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1024 ** 3
        except (ValueError, OSError, AttributeError):
            pass
    return 2.


def process_usage():
    """OS process high-water RSS and CPU, without an optional dependency."""
    peak = None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ['peak_rss', 'rss', 'peak_paged', 'paged',
                    'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile']]
        counters = Counters()
        counters.size = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if query(current(), ctypes.byref(counters), counters.size):
            peak = int(counters.peak_rss)
    else:
        import resource
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if os.sys.platform == 'darwin' else 1024))
    return dict(pid=os.getpid(), cpu_seconds=time.process_time(), peak_rss_bytes=peak)


def worker_count(config):
    requested = config['resources']['cpu_workers']
    if requested:
        return requested
    # Each process has one kernel cache, bounded transform LRU and read tables.
    reserve = 1.5 + config.get('solver', {}).get('cache_size_mb', 0) / 1024
    memory_limit = max(1, int(max(0, available_memory_gb() - 2) / reserve))
    cpu_limit = max(1, (os.cpu_count() or 1) // config['resources']['threads_per_task'])
    return min(8, cpu_limit, memory_limit)


class TaskRunner:
    worker = False

    def record_task(self, task, **fields):
        # Persist physical attempt state BEFORE the logical record. A crash
        # cannot let another analysis mode obtain a fresh retry budget.
        record = dict(task, **fields)
        atomic_json(self.root / '.claims' / task['fit_id'] / 'outcome.json', record)
        return self.journal.record(task, **fields)

    def checkpoint(self):
        if not self.worker:
            self.journal.snapshot()

    def disk_check(self):
        resources = self.config['resources']
        if shutil.disk_usage(self.root).free < resources['minimum_free_gb'] * 1024 ** 3:
            raise ResourceFailure('Insufficient disk space; user data are never cleaned')
        if self.journal.artifact_bytes > resources['max_run_gb'] * 1024 ** 3:
            raise ResourceFailure('Run disk budget reached; increase it explicitly before resuming')

    def monthly(self, task, *, save_package=False):
        # Physical leases also protect aliases and independent duplicate submissions.
        with exclusive_run(self.root / '.claims' / task['fit_id'], wait=True):
            if self.worker:
                self.journal = TaskJournal(self.root, resume=True,
                    max_attempts=self.config['policy']['task_attempts'], task=task)
            return self._monthly_locked(task, save_package=save_package)

    def _monthly_locked(self, task, *, save_package=False):
        completed = self.journal.succeeded(task)
        if completed:
            if save_package and not task['identity']['family'].startswith('naive_') and not (self.root / completed['artifact'] / 'model_package').exists():
                raise RuntimeError('Required selected model package is missing')
            return completed
        self.disk_check()
        old = self.journal.records.get(task['task_id'], {})
        outcome = self.root / '.claims' / task['fit_id'] / 'outcome.json'
        if outcome.exists():
            shared = read_json(outcome)
            physical = lambda record: {k: v for k, v in record['identity'].items() if k != 'mode'}
            if shared['fit_id'] != task['fit_id'] or physical(shared) != physical(task):
                raise RuntimeError('Physical fit claim identity collision')
            if old.get('status') != 'SUCCEEDED' and shared.get('attempts', 0) >= old.get('attempts', 0):
                old = shared
        if old.get('status') == 'FAILED':
            if old.get('failure_kind') in ['ESTIMATOR', 'NUMERICAL', 'CONVERGENCE', 'OPTIMALITY']:
                self.record_task(task, **{k: v for k, v in old.items() if k not in ['task_id', 'fit_id', 'stage', 'identity']})
                raise FitFailure(old['error'], old.get('diagnostics', []))
            if old.get('failure_kind') not in ['IO', 'RESOURCE'] or old.get('attempts', 0) >= self.journal.max_attempts:
                raise RuntimeError('Failed contract/task cannot be silently retried: ' + old['error'])
        artifact = Path(task['stage']) / 'fits' / task['fit_id']
        destination = self.root / artifact
        if old.get('status') == 'SUCCEEDED' and not destination.exists():
            raise RuntimeError('Committed physical fit artifact missing; refusing to refit through an alias')
        physical = {k: v for k, v in task['identity'].items() if k != 'mode'}
        if destination.exists():
            record = read_json(destination / 'artifact.json')
            if record['identity'] != physical:
                raise RuntimeError('Physical fit identity collision')
            check_files(destination, record['files'])
            if save_package and not task['identity']['family'].startswith('naive_') and not (destination / 'model_package').exists():
                raise RuntimeError('Required selected model package is missing')
            return self.record_task(task, status='SUCCEEDED', artifact=artifact.as_posix(),
                files=file_manifest(destination), reused=True,
                attempts=max(h['attempt'] for h in record['result']['attempt_history']),
                artifact_bytes=record['artifact_bytes'], **record['result'])
        attempt = old.get('attempts', 0)
        history = old.get('attempt_history', [])
        interrupted = old.get('status') in ['RUNNING', 'INTERRUPTED'] or old.get('interrupted_fit_calls_unknown', False)
        if attempt >= self.journal.max_attempts:
            raise RuntimeError('Interrupted task exhausted the fixed attempt budget')
        while attempt < self.journal.max_attempts:
            attempt += 1
            self.record_task(task, status='RUNNING', attempts=attempt, attempt_history=history,
                interrupted_fit_calls_unknown=interrupted)
            started = time.perf_counter()
            try:
                with staging(destination) as temporary:
                    result = self.executor(task, temporary, save_package=save_package)
                    result['elapsed_seconds'] = time.perf_counter() - started
                    history.append(dict(attempt=attempt, status='SUCCEEDED',
                        estimator_fit_calls=result['estimator_fit_calls'], calibration_fit_calls=result.get('calibration_fit_calls', 0), elapsed_seconds=result['elapsed_seconds'],
                        diagnostics=result.get('diagnostics', [])))
                    result.update(estimator_fit_calls=sum(h['estimator_fit_calls'] for h in history),
                        calibration_fit_calls=sum(h.get('calibration_fit_calls', 0) for h in history),
                        elapsed_seconds=sum(h.get('elapsed_seconds', 0) for h in history),
                        diagnostics=[d for h in history for d in h.get('diagnostics', [])],
                        attempt_history=history, interrupted_fit_calls_unknown=interrupted)
                    files = file_manifest(temporary)
                    size = sum((temporary / name).stat().st_size for name in files)
                    atomic_json(temporary / 'artifact.json', dict(identity=physical, files=files, artifact_bytes=size, result=result))
                record = self.record_task(task, status='SUCCEEDED', artifact=artifact.as_posix(),
                    files=file_manifest(destination), artifact_bytes=size, reused=False, attempts=attempt, **result)
                if not self.worker and len(self.journal.records) % 100 == 0:
                    self.checkpoint()
                    print('completed logical tasks', len(self.journal.records), flush=True)
                return record
            except FitFailure as error:
                history.append(dict(attempt=attempt, status='FAILED', failure_kind=error.kind,
                    elapsed_seconds=time.perf_counter() - started, **fit_counts(error.diagnostics), diagnostics=error.diagnostics))
                self.record_task(task, status='FAILED', attempts=attempt, error=str(error),
                    failure_kind=error.kind, elapsed_seconds=sum(h.get('elapsed_seconds', 0) for h in history),
                    diagnostics=[d for h in history for d in h.get('diagnostics', [])],
                    estimator_fit_calls=sum(h['estimator_fit_calls'] for h in history),
                        calibration_fit_calls=sum(h.get('calibration_fit_calls', 0) for h in history), attempt_history=history,
                    interrupted_fit_calls_unknown=interrupted)
                if attempt == self.journal.max_attempts:
                    self.checkpoint()
                    raise
            except BaseException as error:
                kind = ('USER_INTERRUPTION' if isinstance(error, KeyboardInterrupt) else
                    'RESOURCE' if isinstance(error, (ResourceFailure, MemoryError)) else
                    'IO' if isinstance(error, OSError) else 'CONTRACT')
                diagnostics = getattr(error, 'diagnostics', getattr(self.executor, 'last_diagnostics', []))
                history.append(dict(attempt=attempt, status='INTERRUPTED' if kind == 'USER_INTERRUPTION' else 'FAILED',
                    failure_kind=kind, elapsed_seconds=time.perf_counter() - started,
                    **fit_counts(diagnostics), diagnostics=diagnostics))
                self.record_task(task, status=history[-1]['status'], attempts=attempt, error=str(error), error_type=type(error).__name__,
                    failure_kind=kind, elapsed_seconds=sum(h.get('elapsed_seconds', 0) for h in history),
                    **{k: sum(h.get(k, 0) for h in history) for k in ['estimator_fit_calls', 'calibration_fit_calls']},
                    diagnostics=[d for h in history for d in h.get('diagnostics', [])],
                    attempt_history=history, interrupted_fit_calls_unknown=interrupted or
                        (isinstance(error, KeyboardInterrupt) and not hasattr(error, 'diagnostics')))
                self.checkpoint()
                raise  # schema, version and artifact failures stop the run immediately


_runner = None


def _initialize_worker(config, data_root, identity, root, worker_factory):
    global _runner
    from ..framework import DataStore
    from .runtime import MonthlyExecutor
    from threadpoolctl import threadpool_limits
    # Hold the limiter for the process lifetime as well as within each adapter.
    global _thread_limit
    _thread_limit = threadpool_limits(limits=config['resources']['threads_per_task'])
    _runner = TaskRunner()
    _runner.worker = True
    _runner.root, _runner.config = Path(root), config
    _runner.executor = worker_factory(config, data_root, identity) if worker_factory else MonthlyExecutor(config, DataStore(data_root), identity)


def _worker_task(item):
    task, keep = item
    # Task records have one writer, under the physical lease. Shared snapshots
    # and all stage/selection manifests are written by the coordinator only.
    try:
        return dict(ok=True, record=_runner.monthly(task, save_package=keep))
    except Exception as error:
        return dict(ok=False, fit_failure=isinstance(error, FitFailure), message=str(error),
            error_type=type(error).__name__, traceback=traceback.format_exc(),
            diagnostics=getattr(error, 'diagnostics', []))


class TaskScheduler:
    def __init__(self, owner, *, worker_factory=None):
        self.owner, self.worker_factory = owner, worker_factory
        self.workers = worker_count(owner.config)
        if owner.artificial and self.workers > 1 and worker_factory is None:
            raise ValueError('Process orchestration tests require an explicit non-learning worker factory')
        self.pool = None

    def map(self, items, *, allow_fit_failure=False):
        grouped = {}
        for task, keep in items:
            group = grouped.setdefault(task['fit_id'], [task, False])
            group[1] = group[1] or keep
        if self.workers == 1:
            results = {}
            for task, keep in grouped.values():
                try:
                    results[task['fit_id']] = self.owner.monthly(task, save_package=keep)
                except FitFailure:
                    if not allow_fit_failure:
                        raise
                    results[task['fit_id']] = None
            return [None if results[t['fit_id']] is None else self.owner.monthly(t, save_package=k) for t, k in items]
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize_worker, initargs=(self.owner.config, str(self.owner.store.root),
                    self.owner.identity, str(self.owner.root), self.worker_factory))
        self.owner.disk_check()
        leaders = list(grouped.values())
        results = {}
        started = heartbeat = time.monotonic()
        try:
            # Bound outstanding work. A stop/failure does not leave a whole
            # search queued; aggregation still follows the original input order.
            pending, cursor = {}, iter(leaders)
            def fill():
                while len(pending) < self.workers * 2:
                    item = next(cursor, None)
                    if item is None:
                        break
                    self.owner.disk_check()
                    pending[self.pool.submit(_worker_task, item)] = item[0]
            fill()
            while pending:
                done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    task = pending.pop(future)
                    packet = future.result()
                    self._accept_packet(task, packet, results, allow_fit_failure)
                now = time.monotonic()
                if now - heartbeat >= 30:
                    elapsed = now - started
                    remaining = len(leaders) - len(results)
                    status = dict(stage=leaders[0][0]['stage'], batch_physical=len(leaders),
                        completed=len(results), remaining=remaining, failed=sum(r is None for r in results.values()),
                        workers=self.workers, batch_wall_seconds=elapsed, available_memory_gb=available_memory_gb(),
                        free_disk_gb=shutil.disk_usage(self.owner.root).free / 1024**3,
                        estimated_remaining_seconds=elapsed * remaining / len(results) if results else None,
                        unix_time=time.time())
                    atomic_json(self.owner.root / 'logs/heartbeat.json', status)
                    print('task batch progress', status, flush=True)
                    heartbeat = now
                fill()
            ordered = []
            for task, keep in items:
                leader = results[task['fit_id']]
                ordered.append(None if leader is None else self.owner.monthly(task, save_package=keep))
            self.owner.journal.snapshot()
            return ordered
        except BaseException:
            for future in locals().get('pending', {}):
                future.cancel()
            self.close()
            self.owner.journal = TaskJournal(self.owner.root, resume=True,
                max_attempts=self.owner.config['policy']['task_attempts'])
            self.owner.journal.snapshot()
            raise

    def _accept_packet(self, task, packet, results, allow_fit_failure):
        path = self.owner.journal.path(task)
        if path.exists():
            self.owner.journal.accept(read_json(path))
        if not packet['ok']:
            atomic_json(self.owner.root / 'logs/worker_failures' / (task['fit_id'] + '-' + str(time.time_ns()) + '.json'),
                dict(task=task, packet=packet))
            if packet['fit_failure'] and allow_fit_failure:
                results[task['fit_id']] = None
                return
            if packet['fit_failure']:
                raise FitFailure(packet['message'], packet['diagnostics'])
            raise RuntimeError('Process task failed: ' + packet['message'])
        results[task['fit_id']] = packet['record']
        self.owner.disk_check()

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None

