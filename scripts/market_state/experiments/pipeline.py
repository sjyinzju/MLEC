"""B search -> selected development -> immutable selection lock -> C -> reports."""
from pathlib import Path
import re
import shutil
import tempfile
import pandas as pd
from ..common import digest
from ..models.elastic_net import FitFailure
from ..release import file_hash
from .artifacts import (TaskJournal, atomic_json, atomic_parquet, read_json, staging,
    file_manifest, check_files, native_path, exclusive_run)
from .config import candidates, seeds, scope, portable_config, validate_config
from .runtime import MonthlyExecutor, preflight, versions, fold_lists
from .warnings import select_workpoints


def group_id(market, task, information):
    return '|'.join([market, task, information])


class Pipeline:
    def __init__(self, config, store, *, suite='full', run_id=None, resume=False,
                 executor=None, preflight_function=None, artificial=False, schedule=None):
        self.config, self.store, self.suite, self.resume = config, store, suite, resume
        self.artificial = artificial
        if artificial:
            if executor is None or config['purpose'] != 'ARTIFICIAL_TEST_ONLY' or not Path(config['output_root']).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise ValueError('Artificial orchestration requires a stub and a temporary test directory')
        else:
            validate_config(config)
            if schedule is not None or executor is not None or preflight_function is not None:
                raise ValueError('Formal execution cannot replace its executor, preflight or folds')
        self.identity = versions(config, store)
        self.run_id = run_id or digest(dict(versions=self.identity, suite=suite, family=config['model']))[:24]
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}', self.run_id):
            raise ValueError('Unsafe run ID')
        self.root = native_path(Path(config['output_root']).resolve() / config['model'] / self.run_id)
        self.development, self.test = schedule if schedule is not None else fold_lists(store)
        self.comparisons = scope(config, store, suite)
        self._executor, self._preflight = executor, preflight_function
        self.journal = TaskJournal(self.root, resume=resume, max_attempts=config['policy']['task_attempts'])

    def initialize(self):
        self.journal = TaskJournal(self.root, resume=self.resume, max_attempts=self.config['policy']['task_attempts'])
        accepted = (self._preflight or preflight)(self.config, self.store, self.suite)
        if self.identity != versions(self.config, self.store):
            raise RuntimeError('Versions changed during initialization')
        path = self.root / 'manifest.json'
        if path.exists():
            if not self.resume:
                raise RuntimeError('Existing run requires --resume')
            manifest = read_json(path)
            if manifest['versions'] != self.identity or manifest['suite'] != self.suite or manifest['purpose'] != self.config['purpose']:
                raise RuntimeError('Cannot resume a different version, purpose or suite')
            if read_json(self.root / 'config.resolved.yaml') != self.config:
                # Moving identical sealed data/output paths is explicitly permitted.
                if portable_config(read_json(self.root / 'config.resolved.yaml')) != portable_config(self.config):
                    raise RuntimeError('Resolved configuration changed')
                atomic_json(self.root / 'config.resolved.yaml', self.config)
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_json(path, dict(run_id=self.run_id, model=self.config['model'], suite=self.suite,
                purpose=self.config['purpose'], versions=self.identity, state='INITIALIZED',
                development_complete=False, test_complete=False, lock_hash=None,
                development_folds=self.development, test_folds=self.test))
            atomic_json(self.root / 'config.resolved.yaml', self.config)
            atomic_json(self.root / 'environment.json', accepted['environment'])
            atomic_json(self.root / 'preflight.json', accepted)
        self.executor = self._executor or MonthlyExecutor(self.config, self.store, self.identity)
        return self

    def assert_current(self):
        manifest = read_json(self.root / 'manifest.json')
        if versions(self.config, self.store) != self.identity or manifest['versions'] != self.identity:
            raise RuntimeError('Run versions changed; refusing stale artifacts')
        return manifest

    def update_state(self, **updates):
        manifest = self.assert_current()
        manifest.update(updates)
        atomic_json(self.root / 'manifest.json', manifest)

    def task(self, *, stage, mode, market, task, information, fold, parameters, seed, family=None):
        identity = dict(family=family or self.config['model'], task=task, market_id=market,
            information_set=information, mode=mode, stage=stage, fold_id=fold,
            parameters=parameters, seed=int(seed), backend=self.config['backend'],
            versions=self.identity, purpose=self.config['purpose'])
        physical = {k: v for k, v in identity.items() if k != 'mode'}
        return dict(task_id=digest(identity), fit_id=digest(physical), stage=stage, identity=identity)

    def disk_check(self):
        resources = self.config['resources']
        if shutil.disk_usage(self.root).free < resources['minimum_free_gb'] * 1024 ** 3:
            raise RuntimeError('Insufficient disk space; user data are never cleaned')
        by_fit = {r['fit_id']: r.get('artifact_bytes', 0) for r in self.journal.records.values() if r['status'] == 'SUCCEEDED'}
        if sum(by_fit.values()) > resources['max_run_gb'] * 1024 ** 3:
            raise RuntimeError('Run disk budget reached; increase it explicitly before resuming')

    def monthly(self, task, *, save_package=False):
        completed = self.journal.succeeded(task)
        if completed:
            return completed
        self.disk_check()
        old = self.journal.records.get(task['task_id'], {})
        if old.get('status') == 'FAILED':
            if old.get('failure_kind') == 'ESTIMATOR':
                raise FitFailure(old['error'], old.get('diagnostics', []))
            if old.get('failure_kind') != 'IO' or old.get('attempts', 0) >= self.journal.max_attempts:
                raise RuntimeError('Failed contract/task cannot be silently retried: ' + old['error'])
        artifact = Path(task['stage']) / 'fits' / task['fit_id']
        destination = self.root / artifact
        physical = {k: v for k, v in task['identity'].items() if k != 'mode'}
        if destination.exists():
            record = read_json(destination / 'artifact.json')
            if record['identity'] != physical:
                raise RuntimeError('Physical fit identity collision')
            check_files(destination, record['files'])
            if save_package and not task['identity']['family'].startswith('naive_') and not (destination / 'model_package').exists():
                raise RuntimeError('Required selected model package is missing')
            return self.journal.record(task, status='SUCCEEDED', artifact=artifact.as_posix(),
                files=file_manifest(destination), reused=True, attempts=0, artifact_bytes=record['artifact_bytes'], **record['result'])
        attempt = old.get('attempts', 0)
        history = old.get('attempt_history', [])
        interrupted = old.get('status') == 'RUNNING' or old.get('interrupted_fit_calls_unknown', False)
        if attempt >= self.journal.max_attempts:
            raise RuntimeError('Interrupted task exhausted the fixed attempt budget')
        while attempt < self.journal.max_attempts:
            attempt += 1
            self.journal.record(task, status='RUNNING', attempts=attempt, attempt_history=history,
                interrupted_fit_calls_unknown=interrupted)
            try:
                with staging(destination) as temporary:
                    result = self.executor(task, temporary, save_package=save_package)
                    history.append(dict(attempt=attempt, status='SUCCEEDED',
                        estimator_fit_calls=result['estimator_fit_calls'], elapsed_seconds=result['elapsed_seconds'],
                        diagnostics=result.get('diagnostics', [])))
                    result.update(estimator_fit_calls=sum(h['estimator_fit_calls'] for h in history),
                        elapsed_seconds=sum(h.get('elapsed_seconds', 0) for h in history),
                        diagnostics=[d for h in history for d in h.get('diagnostics', [])],
                        attempt_history=history, interrupted_fit_calls_unknown=interrupted)
                    files = file_manifest(temporary)
                    size = sum((temporary / name).stat().st_size for name in files)
                    atomic_json(temporary / 'artifact.json', dict(identity=physical, files=files, artifact_bytes=size, result=result))
                record = self.journal.record(task, status='SUCCEEDED', artifact=artifact.as_posix(),
                    files=file_manifest(destination), artifact_bytes=size, reused=False, attempts=attempt, **result)
                if len(self.journal.records) % 100 == 0:
                    self.journal.snapshot()
                    print('completed logical tasks', len(self.journal.records), flush=True)
                return record
            except FitFailure as error:
                history.append(dict(attempt=attempt, status='FAILED', estimator_fit_calls=len(error.diagnostics), diagnostics=error.diagnostics))
                self.journal.record(task, status='FAILED', attempts=attempt, error=str(error),
                    failure_kind='ESTIMATOR',
                    diagnostics=[d for h in history for d in h.get('diagnostics', [])],
                    estimator_fit_calls=sum(h['estimator_fit_calls'] for h in history), attempt_history=history,
                    interrupted_fit_calls_unknown=interrupted)
                if attempt == self.journal.max_attempts:
                    self.journal.snapshot()
                    raise
            except Exception as error:
                self.journal.record(task, status='FAILED', attempts=attempt, error=str(error), error_type=type(error).__name__,
                    failure_kind='IO' if isinstance(error, OSError) else 'CONTRACT',
                    attempt_history=history, interrupted_fit_calls_unknown=True)
                self.journal.snapshot()
                raise  # schema, version and artifact failures stop the run immediately

    def checked_scores(self, record):
        path = self.root / record['artifact']
        check_files(path, record['files'])
        scores = pd.read_parquet(path / 'losses.parquet')
        ctx = read_json(path / 'context.json')
        from ..model_contract import key_hash, truth_hash
        columns = ctx['schema']['columns'][record['identity']['task']]
        if len(scores) != ctx['mature_rows'] or key_hash(scores[['market_id', 'asof_date', 'horizon']]) != ctx['scoring_keys'] or truth_hash(scores[columns]) != ctx['scoring_truth']:
            raise RuntimeError('Incomplete or wrong scoring cohort')
        return scores

    def candidate_score(self, records, task, candidate, expected_months):
        if len(records) != len(expected_months) or any(r is None for r in records):
            return dict(candidate_id=candidate['candidate_id'], parameters=candidate['parameters'], valid=False,
                complexity_order=candidate['complexity_order'], score=None, reason='REQUIRED_MONTH_FAILED', expected_months=expected_months)
        frames = [self.checked_scores(r) for r in records]
        if any(not len(f) for f in frames):
            raise RuntimeError('A development month has no eligible scoring samples')
        scores = pd.concat(frames, ignore_index=True)
        if scores.duplicated(['market_id', 'asof_date', 'horizon']).any():
            raise RuntimeError('Search counted a scoring week twice')
        return dict(candidate_id=candidate['candidate_id'], parameters=candidate['parameters'], valid=True,
            complexity_order=candidate['complexity_order'],
            score=float(scores.loss.mean()), n=len(scores), expected_months=expected_months,
            tasks=[r['task_id'] for r in records], fit_ids=[r['fit_id'] for r in records])

    @staticmethod
    def rank(records, task):
        def order(r):
            return r['score'], tuple(r['complexity_order']), r['candidate_id']
        return sorted([r for r in records if r['valid']], key=order)

    def search_group(self, market, target, information):
        coarse = [f for f in self.development if int(f[-2:]) in self.config['search']['coarse_months']]
        all_candidates = candidates(self.config, target)
        coarse_records = {c['candidate_id']: [] for c in all_candidates}
        def run(c, fold):
            task = self.task(stage='development', mode='search', market=market, task=target,
                information=information, fold=fold, parameters=c['parameters'], seed=self.config['search']['screening_seed'])
            try:
                return self.monthly(task, save_package=fold == self.development[-1])
            except FitFailure:
                return None
        for fold in coarse:
            for c in all_candidates:
                coarse_records[c['candidate_id']].append(run(c, fold))
        scores = [self.candidate_score(coarse_records[c['candidate_id']], target, c, coarse) for c in all_candidates]
        ranked = self.rank(scores, target)
        if len(ranked) < self.config['search']['finalists']:
            raise RuntimeError('Too few complete legal coarse candidates: ' + group_id(market, target, information))
        finalists = ranked[:self.config['search']['finalists']]
        complete = {c['candidate_id']: [] for c in finalists}
        for fold in self.development:
            for c in finalists:
                complete[c['candidate_id']].append(run(c, fold))
        full_scores = [self.candidate_score(complete[c['candidate_id']], target, c, self.development) for c in finalists]
        ranked_full = self.rank(full_scores, target)
        if not ranked_full:
            raise RuntimeError('No legal full-review candidate: ' + group_id(market, target, information))
        return dict(market_id=market, task=target, information_set=information,
            coarse=scores, full_review=full_scores, winner=ranked_full[0],
            selection_metric='log_loss' if target == 'classification' else 'fixed_initial_five_dimension_squared',
            aggregation='actual_scoring_weeks', seed=self.config['search']['screening_seed'])

    def selected_tasks(self, selection, stage):
        folds = self.development if stage == 'development' else self.test
        tasks = []
        for fold in folds:
            for market in self.config['markets']:
                for target in self.config['tasks']:
                    for mode, information in self.comparisons:
                        source = information if mode == 'retuned_core' else 'M+Z'
                        winner = selection[group_id(market, target, source)]['winner']
                        for seed in seeds(self.config, target):
                            tasks.append(self.task(stage=stage, mode=mode, market=market, task=target,
                                information=information, fold=fold, parameters=winner['parameters'], seed=seed))
                    for baseline in (['naive_history', 'naive_current_state'] if target == 'classification' else ['naive_persistence']):
                        tasks.append(self.task(stage=stage, mode='baseline', market=market, task=target, information='M',
                            fold=fold, parameters=self.config['baselines'], seed=0, family=baseline))
        return tasks

    def run_selected(self, selection, stage):
        assignments = []
        last = self.development[-1] if stage == 'development' else self.test[-1]
        for task in self.selected_tasks(selection, stage):
            keep = task['identity']['fold_id'] == last or (stage == 'test' and task['identity']['mode'] == 'retuned_core')
            record = self.monthly(task, save_package=keep)
            self.checked_scores(record)
            assignments.append(dict(task_id=task['task_id'], fit_id=task['fit_id'], artifact=record['artifact'], identity=task['identity']))
        path = self.root / stage / 'selection/assignments.json'
        if path.exists() and read_json(path) != assignments:
            raise RuntimeError('Selected analysis assignments changed')
        atomic_json(path, assignments)
        self.journal.snapshot()
        return assignments

    def run_development(self, *, execute=False):
        if not execute:
            raise ValueError('Explicit --execute is required before fitting')
        manifest = self.assert_current()
        if manifest['development_complete']:
            self.development_evidence()  # validates all saved evidence, never retries old candidates
            return read_json(self.root / 'development/selection/search.json')
        if manifest['lock_hash']:
            raise RuntimeError('Cannot reopen development after selection locking')
        self.update_state(state='DEVELOPMENT_RUNNING')
        selection = {}
        for market in self.config['markets']:
            for target in self.config['tasks']:
                for info in ['M', 'M+Z']:
                    print('development search', market, target, info, flush=True)
                    selection[group_id(market, target, info)] = self.search_group(market, target, info)
                    atomic_json(self.root / 'development/selection/search.partial.json', selection)
        atomic_json(self.root / 'development/selection/search.json', selection)
        self.run_selected(selection, 'development')
        self.update_state(development_complete=True, state='DEVELOPMENT_COMPLETE')
        return selection

    def development_evidence(self):
        manifest = self.assert_current()
        if not manifest['development_complete']:
            raise RuntimeError('Development is incomplete; cannot enter C')
        search_path = self.root / 'development/selection/search.json'
        selection = read_json(search_path)
        expected_groups = {group_id(m, t, i) for m in self.config['markets'] for t in self.config['tasks'] for i in ['M', 'M+Z']}
        if set(selection) != expected_groups:
            raise RuntimeError('Incomplete development selection groups')
        for group, evidence in selection.items():
            task = evidence['task']
            generated = {c['candidate_id']: (c['parameters'], c['complexity_order']) for c in candidates(self.config, task)}
            if {c['candidate_id']: (c['parameters'], c['complexity_order']) for c in evidence['coarse']} != generated:
                raise RuntimeError('Candidate list differs from preregistered generation')
            legal = self.rank(evidence['coarse'], task)
            expected_finalists = {r['candidate_id'] for r in legal[:self.config['search']['finalists']]}
            if len(evidence['coarse']) != self.config['search']['candidate_count'] or len(expected_finalists) != self.config['search']['finalists']:
                raise RuntimeError('Incomplete candidate evidence: ' + group)
            if {r['candidate_id'] for r in evidence['full_review']} != expected_finalists:
                raise RuntimeError('Full review is not the preregistered coarse shortlist')
            for phase, entries in [('coarse', evidence['coarse']), ('full', evidence['full_review'])]:
                months = [f for f in self.development if int(f[-2:]) in self.config['search']['coarse_months']] if phase == 'coarse' else self.development
                for candidate in entries:
                    records = []
                    for fold in months:
                        expected = self.task(stage='development', mode='search', market=evidence['market_id'],
                            task=task, information=evidence['information_set'], fold=fold,
                            parameters=candidate['parameters'], seed=self.config['search']['screening_seed'])
                        record = self.journal.records.get(expected['task_id'])
                        if record is None or record['identity'] != expected['identity'] or record['status'] not in ['SUCCEEDED', 'FAILED']:
                            raise RuntimeError('Search month missing from development evidence')
                        records.append(record if record['status'] == 'SUCCEEDED' else None)
                    recomputed = self.candidate_score(records, task, candidate, months)
                    if recomputed != candidate:
                        raise RuntimeError('Development score evidence modified')
            ranked = self.rank(evidence['full_review'], task)
            if not ranked or evidence['winner'] != ranked[0]:
                raise RuntimeError('Winner differs from full-review selection')
        expected_tasks = self.selected_tasks(selection, 'development')
        assignments_path = self.root / 'development/selection/assignments.json'
        assignments = read_json(assignments_path)
        if [a['task_id'] for a in assignments] != [t['task_id'] for t in expected_tasks]:
            raise RuntimeError('Development selected/group/baseline tasks incomplete')
        for task in expected_tasks:
            record = self.journal.records.get(task['task_id'])
            if record is None or record['status'] != 'SUCCEEDED' or record['identity'] != task['identity']:
                raise RuntimeError('Required development task failed or missing')
            self.checked_scores(record)
        records = {key: record for key, record in sorted(self.journal.records.items()) if record['stage'] == 'development'}
        return dict(search_hash=file_hash(search_path), assignments_hash=file_hash(assignments_path),
            tasks_hash=digest(records), selected_task_count=len(assignments)), selection, assignments

    def lock_payload(self):
        evidence, selection, assignments = self.development_evidence()
        from .reports import analysis_frames
        _, warning, _, _ = analysis_frames(self.root, 'development', self.config['purpose'], artificial=self.artificial)
        points = {}
        keys = ['family', 'market_id', 'task', 'mode', 'information_set', 'seed', 'signal']
        for values, frame in warning.groupby(keys, sort=True):
            name = '|'.join(str(v) for v in values)
            points[name] = select_workpoints(frame, self.config['warning']['burdens'])
        preflight_record = read_json(self.root / 'preflight.json')
        return dict(lock_version='selection-lock-v1', run_id=self.run_id, model=self.config['model'], suite=self.suite,
            purpose=self.config['purpose'], versions=self.identity, development_evidence=evidence,
            parameters={k: v['winner'] for k, v in selection.items()},
            analyses=[dict(mode=mode, information_set=info,
                parameter_reference='own_core_winner' if mode == 'retuned_core' else 'MZ_winner') for mode, info in self.comparisons],
            backend=self.config['backend'], resources=portable_config(self.config)['resources'],
            seeds={t: seeds(self.config, t) for t in self.config['tasks']},
            exception_policy=self.config['policy'], search_rules=self.config['search'],
            evaluation=dict(log_eps=1e-15, brier_divide_by_K=False,
                regression='original_units_then_fixed_initial_scale_then_within_dimension_mean_then_five_dimension_mean',
                fixed_scales=preflight_record['fixed_scales']),
            statistics=self.config['statistics'], warning_rules=self.config['warning'],
            risk_definition=preflight_record['risk_definition'], warning_workpoints=points,
            test_folds=self.test, update_rule='monthly existing train members; only prior mature labels; no test selection')

    def lock(self):
        payload = self.lock_payload()
        locked = dict(payload, content_hash=digest(payload))
        path = self.root / 'selection.lock.json'
        if path.exists():
            if read_json(path) != locked:
                raise RuntimeError('Existing lock is modified or conflicts with development')
        else:
            atomic_json(path, locked)
        self.update_state(lock_hash=file_hash(path), state='LOCKED')
        return locked

    def verify_lock(self, lock_path=None):
        path = Path(lock_path) if lock_path else self.root / 'selection.lock.json'
        if path.resolve() != (self.root / 'selection.lock.json').resolve() or not path.exists():
            raise RuntimeError('The run requires its own existing selection.lock.json')
        manifest = self.assert_current()
        if not manifest['lock_hash'] or manifest['lock_hash'] != file_hash(path):
            raise RuntimeError('Lock missing, modified or unregistered')
        locked = read_json(path)
        payload = {k: v for k, v in locked.items() if k != 'content_hash'}
        if digest(payload) != locked['content_hash'] or payload != self.lock_payload():
            raise RuntimeError('Lock content/development/version validation failed')
        return locked

    def run_test(self, *, execute=False, lock_path=None):
        if not execute:
            raise ValueError('Explicit --execute is required before fitting')
        self.verify_lock(lock_path)
        selection = read_json(self.root / 'development/selection/search.json')
        self.update_state(state='TEST_RUNNING')
        self.run_selected(selection, 'test')
        self.update_state(test_complete=True, state='TEST_COMPLETE')

    def run(self, *, execute=False):
        if not execute:
            raise ValueError('Explicit --execute is required before fitting')
        with exclusive_run(self.root):
            return self._run_authorized()

    def _run_authorized(self):
        self.initialize()
        try:
            self.run_development(execute=True)
            self.lock()
            from .reports import summarize
            summarize(self.root, stage='development', artificial=self.artificial)
            self.run_test(execute=True)
            summarize(self.root, stage='test', artificial=self.artificial)
            self.update_state(state='EXPERIMENT_COMPLETE')
        except Exception as error:
            self.journal.snapshot()
            atomic_json(self.root / 'logs/pipeline_failure.json', dict(error=type(error).__name__, message=str(error),
                run_id=self.run_id, versions=self.identity))
            raise
        return self.root
