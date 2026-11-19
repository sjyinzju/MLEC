"""ARTIFICIAL_TEST_ONLY. No real supervised estimator is ever fitted here."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, ElasticNet
from scripts.market_state.common import CORE, KEY, OUT, digest
from scripts.market_state.framework import DataStore, load_dataset, information_view, paired_losses
from scripts.market_state.model_contract import (fit_inputs, fit_context, transform_inputs, prediction_context,
    classification_output, regression_output, validate_output, PredictionContext)
from scripts.market_state.target_adapters import fit_targets, evaluation_scale
from scripts.market_state.models import REGISTRY, require_model, create_model
from scripts.market_state.models.elastic_net import ElasticNetAdapter, FitFailure
from scripts.market_state.experiments.config import load_config, candidates, scope
from scripts.market_state.experiments.runtime import preview, MonthlyExecutor, versions
from scripts.market_state.experiments.pipeline import Pipeline
from scripts.market_state.experiments.artifacts import read_json, atomic_json, check_files
from scripts.market_state.experiments.scoring import (score_predictions, classification_metrics,
    regression_metrics, synchronized_bootstrap, holm)
from scripts.market_state.experiments.warnings import select_workpoints, evaluate_workpoint


class NonLearningEstimator:
    """A deterministic I/O stub; fit ignores all target and feature values."""
    def __init__(self, classification, maximum, mode='ok'):
        self.classification, self.maximum, self.mode = classification, maximum, mode

    def fit(self, X, y):
        self.n_iter_ = np.array([1]) if self.classification else 1
        self.dual_gap_ = 0.
        self.coef_ = np.zeros((3, X.shape[1])) if self.classification else np.zeros(X.shape[1])
        self.intercept_ = np.zeros(3) if self.classification else 0.
        self.classes_ = np.arange(3)
        if self.mode == 'convergence':
            warnings.warn('ARTIFICIAL convergence failure', ConvergenceWarning)
        if self.mode == 'numeric':
            warnings.warn('ARTIFICIAL numerical failure', RuntimeWarning)
        return self

    def predict_proba(self, X):
        return np.tile([.25, .5, .25], (len(X), 1))

    def predict(self, X):
        return np.zeros(len(X))


@pytest.fixture(scope='module')
def store():
    return DataStore()


def dataset(store, target='classification', role='train', fold='2020-01', info='M+Z'):
    return load_dataset(market_id='000985.SH', task=target, information_set=info,
        role=role, fold_id=fold, store=store)


@pytest.fixture
def stub_factory(monkeypatch):
    calls = []
    def estimator(self, maximum):
        calls.append((self.task, maximum))
        return NonLearningEstimator(self.task == 'classification', maximum)
    monkeypatch.setattr(ElasticNetAdapter, 'estimator', estimator)
    # This fixture tests I/O with deliberately non-learning predictions. Real
    # optimality is exercised independently in test_numerical_optimization.py
    # and by the explicit real technical acceptance command.
    monkeypatch.setattr(ElasticNetAdapter, 'solution_quality', lambda *args: dict(accepted=True, purpose='ARTIFICIAL_TEST_ONLY'))
    return calls


def adapter(store, target):
    train = dataset(store, target)
    pre, target_adapter = fit_inputs(train), fit_targets(train)
    params = candidates(load_config(), target)[0]['parameters']
    model = create_model('elastic_net', task=target, preprocessor=pre, target_adapter=target_adapter,
        training_keys=train.keys, parameters=params, seed=3060, policy=load_config()['policy'])
    return train, pre, target_adapter, model


def test_formal_plan_scope_budget_and_candidate_symmetry(store):
    config = load_config()
    plan = preview(config, store, 'full')
    assert plan['core_configurations'] == 16
    assert plan['selected_configurations'] == 112  # 16 retuned + 96 fixed
    assert len(plan['information_sets']) == 12
    assert len(plan['candidate_monthly_tasks']) == 4 * 2 * 2 * 32 * 12
    assert {r['market_id'] for r in plan['configurations']} == set(config['markets'])
    assert {r['mode'] for r in plan['configurations']} == {'retuned_core', 'fixed_full_params'}
    assert all(b['development_months'] == 36 and b['test_months'] == 47 for b in plan['budgets'])
    for task, key, bounds in [('classification', 'C', [1e-4, 1e4]), ('regression', 'alpha', [1e-5, 10.])]:
        values = candidates(config, task)
        assert len(values) == 32 and len({v['candidate_id'] for v in values}) == 32
        assert [min(v['parameters'][key] for v in values), max(v['parameters'][key] for v in values)] == pytest.approx(bounds)
        assert {v['parameters']['l1_ratio'] for v in values} == set(config['search']['l1_ratios'])
        a = [r['candidate_id'] for r in plan['candidate_monthly_tasks'] if r['task'] == task and r['market_id'] == '000985.SH' and r['information_set'] == 'M']
        b = [r['candidate_id'] for r in plan['candidate_monthly_tasks'] if r['task'] == task and r['market_id'] == '000985.SH' and r['information_set'] == 'M+Z']
        assert a == b
    for extension in config['extensions']:
        with pytest.raises(ValueError, match='not implemented'):
            scope(config, store, extension)
    for family in ['random_forest', 'catboost']:
        assert not REGISTRY[family]['implemented']
        with pytest.raises(ValueError, match='not implemented'):
            require_model(family)


def test_locked_sklearn_api_construction_only(store):
    for target, cls in [('classification', LogisticRegression), ('regression', ElasticNet)]:
        _, _, _, model = adapter(store, target)
        estimator = model.estimator(10)
        assert isinstance(estimator, cls)
        if target == 'classification':
            assert estimator.solver == 'saga' and estimator.l1_ratio == model.parameters['l1_ratio']
            assert estimator.penalty == 'deprecated'
        with pytest.raises(AssertionError, match='forbidden'):
            estimator.fit(pd.DataFrame({'x': [0., 1.]}), np.array([0, 1]))


@pytest.mark.parametrize('target', ['classification', 'regression'])
def test_adapter_full_package_and_strict_predictions(store, stub_factory, target, tmp_path):
    train, pre, target_adapter, model = adapter(store, target)
    model.fit(transform_inputs(pre, train), target_adapter.transform(train.y), fit_context(train))
    pred = dataset(store, target, role='prediction')
    ctx = prediction_context(pred, pre, target_adapter, model_id='elastic_net', model_version=model.model_version_)
    output = model.predict(transform_inputs(pre, pred), ctx)
    validate_output(output, ctx, task=target, schema=pred.target_schema)
    assert len(stub_factory) == (1 if target == 'classification' else 7)
    model.save(tmp_path / 'package')
    loaded = ElasticNetAdapter.load(tmp_path / 'package')
    pd.testing.assert_frame_equal(output, loaded.predict(transform_inputs(pre, pred), ctx))
    assert set(loaded.coefficients().feature) == set(pre.schema_['output_columns']) | {'(intercept)'}
    if target == 'regression':
        assert set(loaded.coefficients().target) == set(CORE)
        np.testing.assert_allclose(output[['predicted_' + c for c in CORE]], np.tile(target_adapter.parameters_['center'], (len(pred.keys), 1)))
    X = transform_inputs(pre, pred)
    for bad in [X[X.columns[::-1]], X.astype('float32'), X.iloc[:-1], X.assign(**{X.columns[0]: np.inf})]:
        with pytest.raises(ValueError):
            loaded.predict(bad, ctx)
    with pytest.raises(ValueError):
        loaded.predict(X, replace(ctx, model_version='wrong'))
    (tmp_path / 'package/coefficients.csv').write_text('tampered', encoding='utf8')
    with pytest.raises(ValueError, match='component modified'):
        ElasticNetAdapter.load(tmp_path / 'package')


@pytest.mark.parametrize('mode', ['convergence', 'numeric'])
def test_convergence_retry_and_numeric_failure_are_not_success(store, monkeypatch, mode):
    train, pre, target, model = adapter(store, 'regression')
    calls = []
    def estimator(self, maximum):
        calls.append(maximum)
        return NonLearningEstimator(False, maximum, mode)
    monkeypatch.setattr(ElasticNetAdapter, 'estimator', estimator)
    with pytest.raises(FitFailure) as error:
        model.fit(transform_inputs(pre, train), target.transform(train.y), fit_context(train))
    assert len(calls) == (2 if mode == 'convergence' else 1)
    assert all(not d['converged'] for d in error.value.diagnostics)
    assert not hasattr(model, 'model_version_')


@pytest.mark.parametrize('error', [MemoryError, OSError, KeyboardInterrupt])
def test_solver_resources_and_io_are_not_invalid_hyperparameters(store, monkeypatch, error):
    train, pre, target, model = adapter(store, 'regression')
    class Throwing(NonLearningEstimator):
        def fit(self, X, y):
            raise error('ARTIFICIAL solver resource/IO failure')
    monkeypatch.setattr(ElasticNetAdapter, 'estimator', lambda self, maximum: Throwing(False, maximum))
    with pytest.raises(error) as caught:
        model.fit(transform_inputs(pre, train), target.transform(train.y), fit_context(train))
    assert len(caught.value.diagnostics) == 1 and not hasattr(model, 'model_version_')


def test_empty_tail_predicts_but_never_scores(store, stub_factory, tmp_path):
    config = load_config()
    config['purpose'] = 'ARTIFICIAL_TEST_ONLY'
    executor = MonthlyExecutor(config, store, versions(config, store))
    task = dict(identity=dict(family='elastic_net', task='regression', market_id='000985.SH',
        information_set='M', stage='test', fold_id='2026-11', mode='retuned_core',
        parameters=candidates(config, 'regression')[0]['parameters'], seed=3060, purpose='ARTIFICIAL_TEST_ONLY'))
    executor(task, tmp_path, save_package=False)
    assert len(pd.read_parquet(tmp_path / 'predictions.parquet')) == 2
    assert len(pd.read_parquet(tmp_path / 'losses.parquet')) == 0
    ctx = read_json(tmp_path / 'context.json')
    assert ctx['scoring_status'] == 'NO_MATURE_SCORE_ROWS' and ctx['unscored_rows'] == 2


def test_artificial_scoring_fixed_dimensions_pairing_and_intervals(store):
    reg = dataset(store, 'regression')
    truth = dataset(store, 'regression', role='validation')
    scale = evaluation_scale(market_id='000985.SH', store=store)
    outputs = []
    for information, multiple in [('M', 2.), ('M+Z', 1.)]:
        tr = information_view(reg, information, store=store)
        va = information_view(truth, information, store=store)
        pre, target = fit_inputs(tr), fit_targets(tr)
        ctx = prediction_context(va, pre, target, model_id='ARTIFICIAL_TEST_ONLY', model_version=information)
        values = truth.y + np.array(scale['scale']) * multiple
        output = regression_output(ctx, values, truth.target_schema)
        outputs.append(score_predictions(output, ctx, va, task='regression', fixed_scale=scale))
    assert outputs[0].loss.to_numpy() == pytest.approx(np.full(len(truth.keys), 4.))
    assert outputs[1].loss.to_numpy() == pytest.approx(np.ones(len(truth.keys)))
    pair = paired_losses(*outputs, task='regression', schema=truth.target_schema)
    assert pair.loss_difference.to_numpy() == pytest.approx(np.full(len(truth.keys), 3.))
    frame = pair[KEY + ['loss_difference']].assign(comparison_id='same')
    inference = synchronized_bootstrap(frame, block_weeks=8, repetitions=20, seed=1)
    assert inference['mean'].iloc[0] == pytest.approx(3.)
    assert inference.lower.iloc[0] == pytest.approx(3.)
    bad = outputs[1].copy()
    bad.loc[0, 'amihud'] += 1.
    with pytest.raises(ValueError, match='Unpaired'):
        paired_losses(outputs[0], bad, task='regression', schema=truth.target_schema)
    with pytest.raises(ValueError, match='Duplicate independent'):
        synchronized_bootstrap(pd.concat([frame, frame]), block_weeks=8, repetitions=20, seed=1)
    np.testing.assert_allclose(holm([.01, .04, .03]), [.03, .06, .06])


def test_warning_workpoints_depend_only_on_development_burden():
    frame = pd.DataFrame(dict(score=[.9, .8, .8, .1], event=[True, False, True, False],
        current_risk=[False, True, True, False], realized_drawdown=[.2, .1, .3, 0.],
        asof_date=pd.to_datetime(['2020-01-03', '2020-01-10', '2020-01-17', '2020-02-07'])))
    point = select_workpoints(frame, [.5])[0]
    assert point['threshold'] == .9 and point['development_burden'] == .25
    assert select_workpoints(frame.assign(event=~frame.event), [.5]) == [point]
    result = evaluate_workpoint(frame, .8)
    assert result['alarm_segments'] == 1 and result['repeat_alarm_windows'] == 2
    assert result['loss_coverage'] == pytest.approx(1.)
    assert evaluate_workpoint(frame.assign(event=False), .8)['reason'] == 'NO_IDENTIFIABLE_EVENT_CONTRAST'


def test_manual_classification_log_floor_brier_and_missing_auc(store):
    train = dataset(store)
    truth = dataset(store, role='validation')
    pre, target = fit_inputs(train), fit_targets(train)
    ctx = prediction_context(truth, pre, target, model_id='ARTIFICIAL_TEST_ONLY', model_version='manual')
    p = np.full((len(truth.keys), 3), .1)
    y = truth.y.future_state_id.astype(int).to_numpy()
    p[np.arange(len(y)), y] = .8
    output = classification_output(ctx, p.argmax(axis=1), p, truth.target_schema)
    scores = score_predictions(output, ctx, truth, task='classification')
    np.testing.assert_allclose(scores.log_loss, -np.log(.8))
    np.testing.assert_allclose(scores.brier, .06)
    assert not scores.log_floor_hit.any()
    p[:] = .5
    p[np.arange(len(y)), y] = 0.
    output = classification_output(ctx, p.argmax(axis=1), p, truth.target_schema)
    scores = score_predictions(output, ctx, truth, task='classification')
    np.testing.assert_allclose(scores.log_loss, -np.log(1e-15))
    assert scores.log_floor_hit.all()
    metric, classes, _, _ = classification_metrics(scores.assign(future_state_id=0), truth.target_schema)
    assert metric['roc_auc_ovr'] is None and metric['auc_reason'] == 'MISSING_CLASS_SUPPORT'
    assert any(c['recall'] is None for c in classes)


def test_single_and_missing_class_rules_are_explicit(store, stub_factory):
    config = load_config()
    for single in [False, True]:
        train = dataset(store)
        y = train.y.copy()
        y['future_state_id'] = 1 if single else y.future_state_id.replace(0, 1)
        train = replace(train, y=y)
        pre, target = fit_inputs(train), fit_targets(train)
        policy = dict(config['policy'], missing_class='error')
        model = ElasticNetAdapter(task='classification', preprocessor=pre, target_adapter=target,
            training_keys=train.keys, parameters=candidates(config, 'classification')[0]['parameters'],
            seed=3060, policy=policy)
        with pytest.raises(FitFailure, match='Single-class|absent'):
            model.fit(transform_inputs(pre, train), target.transform(train.y), fit_context(train))
    assert not stub_factory


def test_calendar_bootstrap_is_synchronized_and_keeps_empty_weeks():
    dates = pd.to_datetime(['2020-01-03', '2020-01-10', '2020-01-31', '2020-02-07'])
    a = pd.DataFrame(dict(comparison_id='a', asof_date=dates, loss_difference=[1., 2., 3., 4.]))
    b = a.assign(comparison_id='b', loss_difference=a.loss_difference * 2)
    result = synchronized_bootstrap(pd.concat([a, b], ignore_index=True), block_weeks=2, repetitions=40, seed=11).set_index('comparison_id')
    assert result.loc['a', 'empty_calendar_weeks'] == 2
    for col in ['mean', 'lower', 'upper']:
        assert result.loc['b', col] == pytest.approx(2 * result.loc['a', col])
    assert result.loc['a', 'p_one_sided'] == result.loc['b', 'p_one_sided']


def test_monthly_pair_reuses_exact_target_and_financial_transforms(store):
    config = load_config()
    executor = MonthlyExecutor(config, store, versions(config, store))
    prepared = []
    for info in ['M', 'M+Z']:
        task = dict(identity=dict(market_id='000985.SH', task='regression', fold_id='2020-01', information_set=info))
        prepared.append(executor.prepare(task))
    m, full = prepared
    pd.testing.assert_frame_equal(m[0].keys, full[0].keys)
    pd.testing.assert_frame_equal(m[0].y, full[0].y)
    assert m[2].adapter_version_ == full[2].adapter_version_
    names = m[1].schema_['output_columns']
    pd.testing.assert_frame_equal(transform_inputs(m[1], m[0]), transform_inputs(full[1], full[0])[names])


def test_formal_config_cannot_use_small_acceptance_budget():
    from scripts.market_state.experiments.config import validate_config
    for key, value in [('candidate_count', 2), ('finalists', 1)]:
        config = load_config()
        config['search'][key] = value
        with pytest.raises(ValueError, match='budget'):
            validate_config(config)


def test_io_interruption_resume_only_completes_unfinished_task(store, stub_factory, tmp_path):
    pipeline = artificial_pipeline(load_config(), store, tmp_path).initialize()
    task = pipeline.task(stage='development', mode='search', market='000985.SH', task='classification',
        information='M', fold='2020-01', parameters=candidates(pipeline.config, 'classification')[0]['parameters'], seed=3060)
    actual = pipeline.executor
    def io_error(*args, **kwargs):
        raise OSError('ARTIFICIAL temporary output failure')
    pipeline.executor = io_error
    with pytest.raises(OSError):
        pipeline.monthly(task)
    record = read_json(pipeline.journal.path(task))
    assert record['status'] == 'FAILED' and record['failure_kind'] == 'IO'
    resumed = artificial_pipeline(load_config(), store, tmp_path).initialize()
    done = resumed.monthly(task)
    assert done['status'] == 'SUCCEEDED' and done['attempts'] == 2
    count = len(stub_factory)
    resumed.monthly(task)
    assert len(stub_factory) == count
    other = resumed.task(stage='development', mode='search', market='000985.SH', task='classification',
        information='M', fold='2020-01', parameters=candidates(pipeline.config, 'classification')[1]['parameters'], seed=3060)
    assert other['fit_id'] != task['fit_id'] and other['task_id'] != task['task_id']


def test_failed_refit_invalidates_old_weights(store, stub_factory, monkeypatch):
    train, pre, target, model = adapter(store, 'classification')
    X, y, ctx = transform_inputs(pre, train), target.transform(train.y), fit_context(train)
    model.fit(X, y, ctx)
    assert hasattr(model, 'model_version_')
    monkeypatch.setattr(ElasticNetAdapter, 'estimator', lambda self, maximum: NonLearningEstimator(True, maximum, 'convergence'))
    with pytest.raises(FitFailure):
        model.fit(X, y, ctx)
    assert not hasattr(model, 'model_version_')


def test_run_lease_prevents_simultaneous_writers(tmp_path):
    from scripts.market_state.experiments.artifacts import exclusive_run
    with exclusive_run(tmp_path):
        with pytest.raises(RuntimeError, match='Another process'):
            with exclusive_run(tmp_path):
                pytest.fail('Second writer acquired an active run')
    with exclusive_run(tmp_path):
        assert (tmp_path / '.run.lock').exists()


def test_task_snapshot_accepts_classification_and_regression_diagnostics(tmp_path):
    from scripts.market_state.experiments.artifacts import TaskJournal
    journal = TaskJournal(tmp_path, resume=True, max_attempts=2)
    for task, iterations in [('classification', [1]), ('regression', 1)]:
        record = dict(task_id=task, fit_id=task, stage='development', identity={'task': task})
        journal.record(record, status='SUCCEEDED', attempt_history=[{'diagnostics': [{'n_iter': iterations}]}])
    journal.snapshot()
    table = pd.read_parquet(tmp_path / 'tasks.parquet')
    assert len(table) == 2 and table.attempt_history_json.str.contains('n_iter').all()


def artificial_pipeline(config, store, tmp_path, *, executor=None, suite='full'):
    c = deepcopy(config)
    c.update(purpose='ARTIFICIAL_TEST_ONLY', output_root=str(tmp_path), markets=['000985.SH'])
    c['search'].update(candidate_count=2, finalists=1, stability_seeds=[3060])
    c['resources'].update(minimum_free_gb=0, max_run_gb=1, cpu_workers=1)
    c['statistics']['repetitions'] = 25
    real_executor = MonthlyExecutor(c, store, versions(c, store))
    def stub(task, destination, *, save_package):
        return real_executor(task, destination, save_package=save_package)
    def preflight_stub(*args):
        return dict(environment={'purpose': 'ARTIFICIAL_TEST_ONLY'},
            fixed_scales=real_executor.scales, risk_definition=real_executor.risk)
    return Pipeline(c, store, run_id='artificial', resume=True, artificial=True, suite=suite,
        executor=executor or stub, preflight_function=preflight_stub,
        schedule=(['2020-01', '2020-02'], ['2023-01']))


@pytest.mark.parametrize('suite', ['core', 'full'])
def test_complete_stub_pipeline_automatic_lock_test_reports_resume(store, stub_factory, tmp_path, suite):
    pipeline = artificial_pipeline(load_config(), store, tmp_path, suite=suite)
    root = pipeline.run(execute=True)
    assert read_json(root / 'manifest.json')['state'] == 'EXPERIMENT_COMPLETE'
    for name in ['core_classification', 'core_regression', 'macro_increment', 'macro_groups', 'warning_value', 'runtime_quality', 'coverage_status']:
        assert (root / 'tables' / (name + '.csv')).exists()
    assert (root / 'report.md').exists() and (root / 'development/report.md').exists()
    assert 'ARTIFICIAL_TEST_ONLY' in (root / 'report.md').read_text(encoding='utf8')
    assert len(list((root / 'figures').glob('*.png'))) >= 6
    assert read_json(root / 'selection.lock.json')['development_evidence']['selected_task_count'] > 0
    groups = pd.read_csv(root / 'tables/macro_groups.csv')
    if suite == 'full':
        assert set(groups.kind) == {'add', 'delete'}
        assert set(groups['mode']) == {'fixed_full_params'}
        assert groups.p_holm.isna().all()
    else:
        assert groups.empty
        assert '96 fixed_full_params configurations were NOT EXECUTED' in (root/'report.md').read_text(encoding='utf8')
    counts_before = len(stub_factory)
    evidence_before = read_json(root / 'development/selection/search.json')
    # Resume consumes only verified successful fits, preserving the lock and selection.
    resumed = artificial_pipeline(load_config(), store, tmp_path, suite=suite)
    resumed.run(execute=True)
    assert len(stub_factory) == counts_before
    assert read_json(root / 'development/selection/search.json') == evidence_before
    tasks = pd.read_parquet(root / 'tasks.parquet')
    assert tasks.fit_id.nunique() < len(tasks) and tasks.task_id.is_unique
    paired = pd.read_parquet(root / 'test/losses/paired_differences.parquet')
    assert not paired.duplicated(['comparison_id', 'asof_date', 'seed']).any()
    # Ordinary reporting refuses artificial records, even when they are otherwise complete.
    from scripts.market_state.experiments.reports import summarize
    with pytest.raises(ValueError, match='excluded'):
        summarize(root)
    lock = (root / 'selection.lock.json').read_bytes()
    try:
        modified = read_json(root / 'selection.lock.json')
        modified['backend'] = 'gpu'
        atomic_json(root / 'selection.lock.json', modified)
        with pytest.raises(RuntimeError, match='modified'):
            resumed.run_test(execute=True)
    finally:
        (root / 'selection.lock.json').write_bytes(lock)
    from scripts.market_state.experiments import runtime
    original = runtime.experiment_code_hash
    try:
        runtime.experiment_code_hash = lambda: 'changed-version'
        with pytest.raises(RuntimeError, match='versions changed'):
            resumed.run_test(execute=True)
    finally:
        runtime.experiment_code_hash = original
    assignment = read_json(root / 'test/selection/assignments.json')[0]
    artifact = root / assignment['artifact'] / 'losses.parquet'
    saved = artifact.read_bytes()
    try:
        artifact.write_bytes(b'wrong-content')
        with pytest.raises(RuntimeError, match='modified artifact'):
            resumed.run_test(execute=True)
    finally:
        artifact.write_bytes(saved)


def test_incomplete_development_missing_lock_and_no_execute_stop_before_c(store, stub_factory, tmp_path):
    pipeline = artificial_pipeline(load_config(), store, tmp_path).initialize()
    with pytest.raises(ValueError, match='--execute'):
        pipeline.run_development()
    assert len(stub_factory) == 0
    with pytest.raises(RuntimeError, match='existing selection'):
        pipeline.run_test(execute=True)
    with pytest.raises(RuntimeError, match='incomplete'):
        pipeline.lock()
    def failure(*args, **kwargs):
        raise FitFailure('ARTIFICIAL development failure', [])
    pipeline.executor = failure
    with pytest.raises(RuntimeError, match='Too few'):
        pipeline.run_development(execute=True)
    assert not read_json(pipeline.root / 'manifest.json')['development_complete']
    with pytest.raises(RuntimeError):
        pipeline.run_test(execute=True)


@pytest.mark.parametrize('command', ['plan', 'pipeline', 'run'])
def test_cli_without_execute_never_initializes_or_fits(monkeypatch, tmp_path, command, capsys):
    from scripts.market_state.experiments.__main__ import main
    def forbidden(*args, **kwargs):
        raise AssertionError('Execution reached without --execute')
    monkeypatch.setattr(Pipeline, 'initialize', forbidden)
    main([command, '--output-root', str(tmp_path / 'not-created')])
    assert not (tmp_path / 'not-created').exists()
    assert 'PLANNED' in capsys.readouterr().out


def test_data_roots_portable_hashes_and_original_seal_unchanged(store, tmp_path):
    import shutil
    from scripts.market_state.release import assert_sealed_products, file_hash, sealed_product_path
    original = file_hash(OUT / 'release/seal.json')
    root = tmp_path / 'non_e_drive' / 'data_root'
    seal = read_json(OUT / 'release/seal.json')
    for relative in list(seal['products']) + ['data/market_state/release/seal.json']:
        source = sealed_product_path(relative, OUT)
        destination = sealed_product_path(relative, root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    assert assert_sealed_products(data_root=root) == store.data_version
    moved = DataStore(root)
    for target in ['classification', 'regression']:
        a, b = dataset(store, target), dataset(moved, target)
        pd.testing.assert_frame_equal(a.X, b.X)
        pd.testing.assert_frame_equal(a.y, b.y)
        assert fit_targets(a).adapter_version_ == fit_targets(b).adapter_version_
    assert file_hash(root / 'release/seal.json') == original == file_hash(OUT / 'release/seal.json')
    (root / 'feature_sets.json').write_text('{}', encoding='utf8')
    with pytest.raises(RuntimeError, match='sealed data changed'):
        DataStore(root)


def test_portable_package_keeps_existing_namespace_and_seal(store, tmp_path, monkeypatch):
    from scripts.market_state.experiments import portable
    from scripts.market_state.experiments.artifacts import native_path
    from scripts.market_state.release import file_hash
    original = portable.read_json
    # A running unit suite cannot yet have its own completed test receipt.
    monkeypatch.setattr(portable, 'assert_interface_accepted', lambda **kwargs: None)
    def receipt(path):
        if Path(path).name == 'test_results.json':
            return dict(exit_code=0, experiment_code_hash=portable.experiment_code_hash())
        return original(path)
    monkeypatch.setattr(portable, 'read_json', receipt)
    bundle = native_path(portable.package(tmp_path / 'bundle', store))
    manifest = original(bundle / 'package.manifest.json')
    check_files(bundle, manifest['files'])
    assert (bundle / 'scripts/market_state/experiments/__main__.py').is_file()
    for name in ['START_WINDOWS.cmd', 'START_LINUX.sh', 'README_START_HERE.md']:
        assert name in manifest['files'] and (bundle / name).is_file()
    assert not (bundle / 'scripts/__init__.py').exists()
    assert file_hash(bundle / 'data/market_state/release/seal.json') == file_hash(OUT / 'release/seal.json')
    assert not (bundle / '.local_deps').exists()


@pytest.mark.parametrize('configured_root,cli_override', [(None, False), ('alternate_data', False), ('alternate_data', True)])
def test_smoke_data_root_defaults_and_override_without_training(monkeypatch, tmp_path, configured_root, cli_override):
    from types import SimpleNamespace
    from scripts.market_state.common import ROOT
    from scripts.market_state.experiments import smoke as module
    smoke_config = read_json(ROOT / 'config/experiments/smoke.yaml')
    if configured_root is None:
        smoke_config.pop('data_root', None)
    else:
        smoke_config['data_root'] = configured_root
    override = tmp_path / 'cli_data' if cli_override else None
    expected = override or ROOT / (configured_root or load_config()['data_root'])
    seen = []
    class ConfigChecked(Exception):
        pass
    def stop_before_any_read_or_fit(root):
        seen.append(Path(root))
        raise ConfigChecked
    monkeypatch.setattr(module, 'read_json', lambda path: deepcopy(smoke_config))
    monkeypatch.setattr(module, 'environment', lambda: None)
    monkeypatch.setattr(module, 'DataStore', stop_before_any_read_or_fit)
    args = SimpleNamespace(config=Path('unused'), execute=True, data_root=override, cpu_threads=None)
    # Stop at the configuration boundary: no data read, estimator or real smoke.
    with pytest.raises(ConfigChecked):
        module.smoke(args)
    assert seen == [expected]
