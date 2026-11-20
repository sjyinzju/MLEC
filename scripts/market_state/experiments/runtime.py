"""Read-only preflight and monthly execution through the existing model contract."""
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
import importlib.metadata
import platform
import shutil
import sys
import tempfile
import time
import numpy as np
import pandas as pd
from ..common import ROOT, OUT, CORE, KEY, digest
from ..framework import DataStore, load_dataset, information_view, target_view
from ..model_contract import (CONTRACT_VERSION, fit_inputs, restrict_inputs, transform_inputs, fit_context,
    prediction_context, classification_output, regression_output, key_hash, truth_hash, validate_output)
from ..target_adapters import fit_targets, evaluation_scale
from ..interface_acceptance import assert_interface_accepted
from ..release import file_hash, code_hash
from ..models import require_model, create_model, REGISTRY
from ..models.errors import fit_counts
from ..models.training import TrainingPartitions
from .artifacts import atomic_json, atomic_parquet, read_json, staging, file_manifest, check_files
from .config import portable_config, candidates, seeds, scope, parameter_reference
from .scoring import score_predictions
from .warnings import risk_definition, warning_data
from .scheduling import worker_count, process_usage
from ..preprocessing import input_diagnostics

EXPERIMENT_VERSION = 'experiment-runtime-v2'


def experiment_code_hash():
    paths = sorted(p for name in ['models', 'experiments'] for p in (ROOT / 'scripts/market_state' / name).rglob('*.py'))
    paths += [ROOT / 'requirements-experiments.txt', ROOT / 'requirements-research.txt']
    return digest({p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths})


def environment():
    versions = {}
    requirements = []
    for name in ['requirements-research.txt', 'requirements-experiments.txt']:
        for line in (ROOT / name).read_text(encoding='utf8').splitlines():
            if '==' in line and not line.startswith('#'):
                requirements.append(line.strip())
    for item in requirements:
        name, expected = item.split('==')
        installed = importlib.metadata.version(name)
        if installed != expected:
            raise RuntimeError(f'Dependency {name} must be {expected}; found {installed}')
        versions[name] = installed
    return dict(python=sys.version, platform=platform.platform(), packages=versions, backend='cpu')


def versions(config, store):
    return dict(runtime_version=EXPERIMENT_VERSION, contract_version=CONTRACT_VERSION,
        data_version=store.data_version, feature_version=store.spec['feature_version'],
        target_version=store.spec['target_version'], dictionary_version=store.spec['label_version'],
        original_seal_hash=file_hash(store.root / 'release/seal.json'), interface_code_hash=code_hash(),
        experiment_code_hash=experiment_code_hash(),
        protocol_hash=file_hash(ROOT / 'docs/MLEC_research_protocol.md'),
        experiment_plan_hash=file_hash(ROOT / 'docs/MLEC_experiment_plan.md'),
        config_hash=digest(portable_config(config)))


def fold_lists(store):
    task_config = read_json(store.root / 'data_task_config.json')
    if set(task_config['markets']) != set(store.spec['by_market']) or set(task_config['information_sets']) != set(store.spec['sets']) or not {'classification', 'regression'} <= set(task_config['targets']):
        raise ValueError('Data task configuration differs from the sealed research matrix')
    plans = store.get('time_splits').sort_values('fold_id')
    development = plans.loc[plans.period.eq('validation'), 'fold_id'].tolist()
    test = plans.loc[plans.period.eq('test'), 'fold_id'].tolist()
    if development != [f'{y}-{m:02}' for y in range(2020, 2023) for m in range(1, 13)]:
        raise ValueError('Development folds differ from the research protocol')
    if not test or test[0] != '2023-01':
        raise ValueError('Test must start in January 2023')
    return development, test


def calibration_plans(config, store):
    if config['model'] != 'rbf_svm':
        return []
    cache_key = digest(dict(rules=config['calibration'], markets=config['markets'], quality=config['quality']))
    if not hasattr(store, '_calibration_plans'):
        store._calibration_plans = {}
    if cache_key not in store._calibration_plans:
        development, test = fold_lists(store)
        records = []
        for market in config['markets']:
            for fold in development + test:
                train = load_dataset(market_id=market, information_set='M+Z', task='classification',
                    fold_id=fold, role='train', quality=config['quality'], store=store)
                plan = TrainingPartitions(train).validate_plan(config['calibration'])
                records.append(dict(market_id=market, fold_id=fold, training_keys_hash=key_hash(train.keys),
                    class_count=len(train.target_schema['class_ids']),
                    internal_svc_fits=sum(b['status'] == 'ACCEPTED' for b in plan),
                    sigmoid_fits=len(train.target_schema['class_ids']), final_svc_fits=1, blocks=plan))
        store._calibration_plans[cache_key] = records
    return store._calibration_plans[cache_key]


def preview(config, store, suite):
    comparisons = scope(config, store, suite)
    development, test = fold_lists(store)
    search = config['search']
    coarse = [m for m in development if int(m[-2:]) in search['coarse_months']]
    configurations = [dict(model=config['model'], market_id=m, task=t, mode=mode, information_set=info,
        parameter_source=parameter_reference(mode, info),
        seeds=seeds(config, t), development_months=len(development), test_months=len(test),
        estimators_per_month=7 if t == 'regression' and REGISTRY[config['model']]['regression'] == 'per_target' else 1)
        for m in config['markets'] for t in config['tasks'] for mode, info in comparisons]
    budget = []
    time_plans = calibration_plans(config, store)
    fit_expansion = []
    for t in config['tasks']:
        groups = len(config['markets']) * 2
        candidate_months = groups * (search['candidate_count'] * len(coarse) + search['finalists'] * (len(development) - len(coarse)))
        physical_configurations = len({(info, parameter_reference(mode, info)) for mode, info in comparisons})
        selected_physical = len(config['markets']) * physical_configurations * len(seeds(config, t))
        # Core seed 3060 winners and complete MZ fixed-mode references reuse actual fits.
        selected_b = selected_physical * len(development) - groups * len(development)
        selected_c = selected_physical * len(test)
        outer = candidate_months + selected_b + selected_c
        factor = 7 if t == 'regression' and REGISTRY[config['model']]['regression'] == 'per_target' else 1
        inner, calibration_calls = 0, 0
        if t == 'classification' and time_plans:
            for row in time_plans:
                f = row['fold_id']
                candidate_outer = 2 * (search['candidate_count'] if f in coarse else search['finalists']) if f in development else 0
                selected_outer = physical_configurations * len(seeds(config, t)) - (2 if f in development else 0)
                physical_outer = candidate_outer + selected_outer
                inner += physical_outer * row['internal_svc_fits']
                calibration_calls += physical_outer * row['sigmoid_fits']
                fit_expansion.append(dict(market_id=row['market_id'], fold_id=f,
                    candidate_monthly_fits_upper=candidate_outer, selected_new_monthly_fits_upper=selected_outer,
                    internal_svc_per_fit=row['internal_svc_fits'], final_svc_per_fit=1,
                    sigmoid_per_fit=row['sigmoid_fits'], internal_svc_fits_upper=physical_outer * row['internal_svc_fits'],
                    final_svc_fits_upper=physical_outer, sigmoid_fits_upper=physical_outer * row['sigmoid_fits']))
        estimator_calls = outer * factor + inner
        budget.append(dict(task=t, coarse_months=len(coarse), development_months=len(development), test_months=len(test),
            candidate_monthly_fits_upper=candidate_months, selected_development_new_fits_upper=selected_b,
            test_monthly_fits_upper=selected_c, estimator_fit_calls_upper=estimator_calls,
            internal_svc_fit_calls_upper=inner, final_svc_fit_calls_upper=outer if t == 'classification' and time_plans else 0,
            svr_fit_calls_upper=outer * factor if t == 'regression' and config['model'] == 'rbf_svm' else 0,
            estimator_calls_including_convergence_retries_upper=estimator_calls * (1 + config['policy']['convergence_retries']),
            estimator_calls_including_all_retries_upper=estimator_calls * (1 + config['policy']['convergence_retries']) * config['policy']['task_attempts'],
            calibration_fits=calibration_calls,
            calibration_calls_including_all_retries_upper=calibration_calls * config['policy']['task_attempts'],
            total_fit_calls_including_all_retries_upper=(estimator_calls * (1 + config['policy']['convergence_retries']) + calibration_calls) * config['policy']['task_attempts'],
            note='Upper bound; selected M may also share full parameters. Seeds are not independent samples.'))
    return dict(status='PLANNED', model=config['model'], suite=suite, versions=versions(config, store),
        core_configurations=16, selected_configurations=len(configurations), information_sets=list(store.spec['sets']),
        configurations=configurations, budgets=budget, calibration_plans=time_plans, calibration_fit_expansion=fit_expansion,
        candidates={t: candidates(config, t) for t in config['tasks']},
        candidate_monthly_tasks=[dict(market_id=m, task=t, information_set=i, fold_id=f,
            candidate_id=c['candidate_id'], parameters=c['parameters'], seed=search['screening_seed'])
            for m in config['markets'] for t in config['tasks'] for i in ['M', 'M+Z']
            for c in candidates(config, t) for f in coarse],
        extensions=config['extensions'], supervised_fit_calls=0, calibration_fit_calls=0)


def preflight(config, store, suite, *, check_environment=True):
    require_model(config['model'], config['backend'])
    assert_interface_accepted(data_root=store.root)
    tests = read_json(ROOT / 'reports/market_state/model_io/test_results.json')
    if tests.get('experiment_code_hash') != experiment_code_hash() or tests.get('exit_code') != 0:
        raise RuntimeError('Experiment code changed; complete the non-training full pytest suite before execution')
    scope(config, store, suite)
    development, test = fold_lists(store)
    env = environment() if check_environment else {'purpose': 'ARTIFICIAL_TEST_ONLY'}
    output = Path(config['output_root']).resolve()
    if output.is_relative_to(store.root.resolve()):
        raise ValueError('Results cannot be written inside the read-only data root')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mlec-write-check-', dir=output) as temporary:
        (Path(temporary) / 'write_check').write_bytes(b'mlec')
    if shutil.disk_usage(output).free < config['resources']['minimum_free_gb'] * 1024 ** 3:
        raise RuntimeError('Insufficient free output space')
    support = []
    # Every outer TRAIN cohort is checked; test scores never enter preflight decisions.
    for market in config['markets']:
        for fold in development + test:
            train = load_dataset(market_id=market, information_set='M+Z', task='classification',
                fold_id=fold, role='train', quality=config['quality'], store=store)
            count = train.y.future_state_id.value_counts()
            if len(count) < 2 or (config['policy']['missing_class'] == 'error' and len(count) != len(train.target_schema['class_ids'])):
                raise ValueError('Insufficient class support in outer train: ' + market + ' ' + fold)
            support.append(dict(market_id=market, fold_id=fold, rows=len(train.keys),
                training_keys_hash=key_hash(train.keys), counts={str(int(k)): int(v) for k, v in count.items()}))
            if fold in [development[0], test[0], test[-1]]:
                pre = fit_inputs(train)
                m = information_view(train, 'M', store=store)
                restricted = restrict_inputs(pre, m)
                direct = fit_inputs(m)
                np.testing.assert_array_equal(transform_inputs(restricted, m), transform_inputs(direct, m))
                reg = target_view(train, 'regression', store=store)
                target = fit_targets(reg)
                fit_targets(train)
                np.testing.assert_allclose(target.inverse_transform(target.transform(reg.y)), reg.y, rtol=1e-12, atol=1e-24)
                pred = load_dataset(market_id=market, information_set='M+Z', fold_id=fold,
                    role='prediction', quality=config['quality'], store=store)
                transform_inputs(pre, pred)
    lineage = store.get('macro/' + config['quality'] + '/lineage')
    if lineage.available_at.gt(lineage.asof_time).any():
        raise ValueError('Macro source available after prediction time')
    macro_audit = []
    specifications = {s['series_id']: s for s in read_json(store.root / 'macro/specifications.json')}
    for series, rows in lineage.groupby('series_id'):
        spec = specifications[series]
        age = (rows.asof_time - rows.available_at).dt.total_seconds() / 86400
        macro_audit.append(dict(series_id=series, group=spec['series_group'], frequency=spec['frequency'],
            source_priority=spec['source_priority'], unit=spec['unit'], historical_scopes=sorted(rows.statistical_scope_id.dropna().unique()),
            rows=len(rows), statuses=rows.status.value_counts().to_dict(), median_age_days=float(age.median()) if age.notna().any() else None,
            source_quality=rows.quality.value_counts().to_dict(),
            reconstruction_before_archive_vintage=int(rows.available_at.lt(rows.actual_vintage_available_at).sum()),
            scope_breaks=int(rows.change_scope_break.sum()), period_gaps=int(rows.change_period_gap.sum())))
    return dict(status='PREFLIGHT_PASSED', environment=env, versions=versions(config, store),
        calibration_plans=calibration_plans(config, store),
        train_class_support=support, risk_definition=risk_definition(store, config), macro_lineage_audit=macro_audit,
        resources=dict(config['resources'], resolved_cpu_workers=worker_count(config)),
        fixed_scales={m: evaluation_scale(market_id=m, store=store) for m in config['markets']},
        supervised_fit_calls=0, calibration_fit_calls=0, smoke_runs=0)


class MonthlyExecutor:
    def __init__(self, config, store, identity):
        self.config, self.store, self.identity = config, store, identity
        self.cache = OrderedDict()
        self.cache_stats = dict(context_hits=0, context_misses=0, matrix_hits=0, matrix_misses=0)
        self.last_diagnostics = []
        self.risk = risk_definition(store, config)
        self.scales = {m: evaluation_scale(market_id=m, store=store) for m in config['markets']}

    def prepare(self, task):
        i = task['identity']
        key = (i['market_id'], i['task'], i['fold_id'], self.config['quality'], digest(self.identity))
        if key not in self.cache:
            train = load_dataset(market_id=i['market_id'], task=i['task'], information_set='M+Z',
                fold_id=i['fold_id'], role='train', quality=self.config['quality'], store=self.store)
            pre, target = fit_inputs(train), fit_targets(train)
            pred = load_dataset(market_id=i['market_id'], task=i['task'], information_set='M+Z',
                fold_id=i['fold_id'], role='prediction', quality=self.config['quality'], store=self.store)
            self.cache[key] = dict(full=(train, pre, target, pred), views={}, matrices={})
            self.cache_stats['context_misses'] += 1
            if len(self.cache) > self.config['resources']['transform_cache_entries']:
                self.cache.popitem(last=False)
        else:
            self.cache_stats['context_hits'] += 1
        self.cache.move_to_end(key)
        entry = self.cache[key]
        info = i['information_set']
        if info not in entry['views']:
            full_train, full_pre, target, full_prediction = entry['full']
            train = information_view(full_train, info, store=self.store)
            pre = restrict_inputs(full_pre, train)
            pred = information_view(full_prediction, info, store=self.store)
            entry['views'][info] = train, pre, target, pred
        return entry['views'][info]

    def matrices(self, task):
        if task['identity'].get('versions', self.identity) != self.identity:
            raise ValueError('Matrix cache task version mismatch')
        train, pre, target, pred = self.prepare(task)
        entry = next(reversed(self.cache.values()))
        info = task['identity']['information_set']
        if info not in entry['matrices']:
            entry['matrices'][info] = transform_inputs(pre, train), transform_inputs(pre, pred)
            self.cache_stats['matrix_misses'] += 1
        else:
            self.cache_stats['matrix_hits'] += 1
        return train, pre, target, pred, *entry['matrices'][info]

    def __call__(self, task, destination, *, save_package):
        i = task['identity']
        start = time.perf_counter()
        self.last_diagnostics = []
        train, pre, target, pred, X, Xp = self.matrices(task)
        context = fit_context(train)
        model_id = i['family']
        if model_id.startswith('naive_'):
            model = None
            model_version = digest(dict(family=model_id, context=asdict(context), parameters=i['parameters']))
            ctx = prediction_context(pred, pre, target, model_id=model_id, model_version=model_version, input_matrix=Xp)
            if i['task'] == 'classification':
                ids = target.schema_['class_ids']
                if model_id == 'naive_current_state':
                    p = pred.X[['current_state_prob_' + str(c) for c in ids]].to_numpy(float)
                else:
                    if model_id == 'naive_initial_frequency':
                        frequency = [self.risk['initial_class_frequency'][i['market_id']][str(c)] for c in ids]
                    else:
                        alpha = self.config['baselines']['history_dirichlet_alpha'] if model_id == 'naive_history' else 0.
                        counts = train.y.future_state_id.value_counts().reindex(ids, fill_value=0).to_numpy() + alpha
                        frequency = counts / counts.sum()
                    p = np.tile(frequency, (len(pred.keys), 1))
                output = classification_output(ctx, np.asarray(ids)[p.argmax(axis=1)], p, target.schema_)
            else:
                values = pred.X[['market__' + c + '_20d' for c in CORE]].copy()
                values.columns = CORE
                output = regression_output(ctx, values.reset_index(drop=True), target.schema_)
            diagnostics = []
        else:
            extra = dict(solver=self.config['solver'], calibration=self.config['calibration'],
                training_service=TrainingPartitions(train) if i['task'] == 'classification' else None) if model_id == 'rbf_svm' else {}
            model = create_model(model_id, task=i['task'], preprocessor=pre, target_adapter=target,
                training_keys=train.keys, parameters=i['parameters'], seed=i['seed'], policy=self.config['policy'],
                threads=self.config['resources']['threads_per_task'], **extra)
            model.fit(X, target.transform(train.y), context)
            self.last_diagnostics = model.diagnostics_
            ctx = prediction_context(pred, pre, target, model_id=model_id, model_version=model.model_version_, input_matrix=Xp)
            output = model.predict(Xp, ctx)
            diagnostics = model.diagnostics_
        validate_output(output, ctx, task=i['task'], schema=target.schema_)
        # Output is committed to staging before the first read of this month's Y.
        atomic_parquet(destination / 'predictions.parquet', output)
        truth = load_dataset(market_id=i['market_id'], task=i['task'], information_set=i['information_set'],
            fold_id=i['fold_id'], role='validation' if i['stage'] == 'development' else 'test',
            quality=self.config['quality'], store=self.store)
        scores = score_predictions(output, ctx, truth, task=i['task'], fixed_scale=self.scales[i['market_id']])
        atomic_parquet(destination / 'losses.parquet', scores)
        warning = warning_data(scores, pred, self.store, self.risk, i['task'])
        atomic_parquet(destination / 'warning.parquet', warning)
        if model is not None:
            if hasattr(model, 'diagnostic_artifact'):
                atomic_json(destination / 'kernel_diagnostics.json', model.diagnostic_artifact())
            if hasattr(model, 'coefficients'):
                model.coefficients().to_csv(destination / 'coefficients.csv', index=False)
            if hasattr(model, 'dual_certificates'):
                certificate = model.dual_certificates()
                if len(certificate):
                    atomic_parquet(destination / 'solver_certificates.parquet', certificate)
            if save_package:
                model.save(destination / 'model_package')
        atomic_json(destination / 'context.json', dict(fit=asdict(context),
            prediction={k: v for k, v in asdict(ctx).items() if k != 'keys'},
            prediction_keys=key_hash(pred.keys), scoring_keys=key_hash(truth.keys), scoring_truth=truth_hash(truth.y),
            schema=target.schema_, fixed_scale=self.scales[i['market_id']],
            expected_predictions=len(pred.keys), actual_predictions=len(output), mature_rows=len(scores),
            unscored_rows=len(output) - len(scores), scoring_status='SCORED' if len(scores) else 'NO_MATURE_SCORE_ROWS',
            elapsed_seconds=time.perf_counter() - start, diagnostics=diagnostics,
            input_diagnostics=dict(train=input_diagnostics(X), prediction=input_diagnostics(Xp)),
            cache_statistics=dict(self.cache_stats),
            **fit_counts(diagnostics), purpose=i['purpose']))
        return dict(predictions=len(output), mature_rows=len(scores), elapsed_seconds=time.perf_counter() - start,
            process_usage=process_usage(), cache_statistics=dict(self.cache_stats),
            **fit_counts(diagnostics), diagnostics=diagnostics)
