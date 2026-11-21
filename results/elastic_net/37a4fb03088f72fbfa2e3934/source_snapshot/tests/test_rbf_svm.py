"""Non-learning SVM/optimization stubs only; ordinary pytest never trains."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import os
import numpy as np
import pandas as pd
import pytest
from sklearn.svm import SVC, SVR
from scripts.market_state.common import CORE, digest
from scripts.market_state.framework import DataStore, load_dataset, information_view
from scripts.market_state.model_contract import fit_inputs, fit_context, transform_inputs, prediction_context, training_partition, key_hash
from scripts.market_state.target_adapters import fit_targets
from scripts.market_state.models import create_model
from scripts.market_state.models.errors import FitFailure
from scripts.market_state.models.rbf_svm import RBFSVMAdapter, relative_gamma
from scripts.market_state.models.training import TrainingPartitions
from scripts.market_state.models.calibration import TimeSigmoid, decision_columns, sigmoid_objective
from scripts.market_state.experiments.config import load_config, candidates, seeds, validate_config, portable_config
from scripts.market_state.experiments.runtime import MonthlyExecutor, versions, preview
from scripts.market_state.experiments.pipeline import Pipeline
from scripts.market_state.experiments.scheduling import TaskScheduler, worker_count
from scripts.market_state.experiments.artifacts import read_json, atomic_json, TaskJournal


def svm_config():
    return load_config('config/experiments/rbf_svm.yaml')


class KernelStub:
    def __init__(self, classification, gamma, mode='ok'):
        self.classification, self._gamma, self.mode = classification, gamma, mode

    def fit(self, X, y):
        self.classes_ = np.arange(3)
        self.support_ = np.arange(min(3, len(X)))
        self.support_vectors_ = X.to_numpy()[self.support_]
        self.n_support_ = np.ones(3, dtype=int) if self.classification else np.array([len(self.support_)])
        self.dual_coef_ = np.zeros((1, len(self.support_)))
        self.intercept_ = np.array([0.])
        self.fit_status_, self.n_iter_ = (1 if self.mode == 'convergence' else 0), np.array([1])
        if self.mode == 'numeric':
            self.intercept_[0] = np.nan
        return self

    def decision_function(self, X):
        return np.tile([-.8, .3, .1], (len(X), 1))

    def predict(self, X):
        return np.zeros(len(X))


def stub_estimator(self, maximum, gamma):
    return KernelStub(self.task == 'classification', gamma)


def stub_optimizer(self, scores, target, initial):
    # Fixed non-learning parameters. It never minimizes a likelihood.
    return SimpleNamespace(x=np.array([1., 0.]), fun=1., jac=np.zeros(2), success=True,
        nit=0, status=0, message='NON_LEARNING_OPTIMIZER_STUB')


@pytest.fixture
def stubs(monkeypatch):
    calls = []
    def estimator(self, maximum, gamma):
        calls.append(dict(task=self.task, max_iter=maximum, gamma=gamma))
        return stub_estimator(self, maximum, gamma)
    monkeypatch.setattr(RBFSVMAdapter, 'estimator', estimator)
    monkeypatch.setattr(TimeSigmoid, 'optimize', stub_optimizer)
    return calls


@pytest.fixture(scope='module')
def store():
    return DataStore()


def ds(store, task='classification', fold='2020-01', role='train', info='M'):
    return load_dataset(market_id='000985.SH', information_set=info, task=task, fold_id=fold, role=role, store=store)


def model_for(train):
    c = svm_config()
    task = 'classification' if len(train.y.columns) == 1 else 'regression'
    pre, target = fit_inputs(train), fit_targets(train)
    model = create_model('rbf_svm', task=task, preprocessor=pre, target_adapter=target,
        training_keys=train.keys, parameters=candidates(c, task)[0]['parameters'], seed=3060,
        policy=c['policy'], solver=c['solver'], calibration=c['calibration'],
        training_service=TrainingPartitions(train) if task == 'classification' else None)
    return pre, target, model


def test_svm_config_candidates_seeds_and_legal_api(store):
    c = svm_config()
    validate_config(c)
    for task in c['tasks']:
        values = candidates(c, task)
        assert len(values) == len({x['candidate_id'] for x in values}) == 48
        assert values == candidates(deepcopy(c), task)
        assert seeds(c, task) == [3060]
        assert [min(v['parameters']['C'] for v in values), max(v['parameters']['C'] for v in values)] == [.001, 1000.]
        assert {v['parameters']['gamma_factor'] for v in values} == {.01, .1, 1., 10., 100.}
        assert all('alpha' not in v['parameters'] and 'l1_ratio' not in v['parameters'] for v in values)
        _, _, model = model_for(ds(store, task))
        e = model.estimator(100000, .1)
        assert isinstance(e, SVC if task == 'classification' else SVR)
        assert e.kernel == 'rbf' and e.tol == .001
        if task == 'classification':
            assert not e.probability and e.decision_function_shape == 'ovr'
        else:
            assert min(v['parameters']['epsilon'] for v in values) == .001
            assert max(v['parameters']['epsilon'] for v in values) == 1.
        with pytest.raises(AssertionError, match='forbidden'):
            e.fit(np.zeros((3, 2)), np.arange(3))
    for change in [('candidate_count', 32), ('gamma_factors', [1.]), ('tie_rule', 'elastic_net')]:
        bad = deepcopy(c); bad['search'][change[0]] = change[1]
        with pytest.raises(ValueError): validate_config(bad)
    c2 = deepcopy(c); c2['resources']['cpu_workers'] = 4
    assert portable_config(c2) == portable_config(c)


def test_training_only_plan_maturity_member_restriction_and_paired_blocks(store):
    c = svm_config(); train = ds(store, info='M+Z'); service = TrainingPartitions(train)
    plan = service.validate_plan(c['calibration'])
    m = information_view(train, 'M', store=store)
    assert plan == TrainingPartitions(m).validate_plan(c['calibration'])
    assert any(b['status'] == 'SKIPPED' for b in plan)
    seen = set()
    for b in plan:
        if b['status'] != 'ACCEPTED': continue
        inner, val = service.partition(b)
        assert inner.metadata.label_available_at.le(pd.Timestamp(b['fit_cutoff'])).all()
        assert val.metadata.asof_time.gt(pd.Timestamp(b['fit_cutoff'])).all()
        keys = set(val.keys.asof_date)
        assert not keys & seen; seen |= keys
        assert set(inner.keys.asof_date) <= set(train.keys.asof_date)
        # Prove preprocessing starts from this raw inner training cohort.
        pre = fit_inputs(inner)
        assert pre.fit_context_['training_keys_hash'] == key_hash(inner.keys)
        assert pre.fit_context_['training_keys_hash'] != key_hash(train.keys)
        transform_inputs(pre, val)
    outer_val = ds(store, role='validation')
    with pytest.raises(ValueError, match='formal training'):
        TrainingPartitions(outer_val)
    with pytest.raises(ValueError, match='outside outer'):
        training_partition(train, outer_val.keys, role='train', fit_cutoff=train.metadata.fit_cutoff.iloc[0])
    b = next(b for b in plan if b['status'] == 'ACCEPTED')
    late = train.keys[train.metadata.label_available_at.gt(pd.Timestamp(b['fit_cutoff']))].iloc[:1].reset_index(drop=True)
    with pytest.raises(ValueError, match='Immature'):
        training_partition(train, late, role='train', fit_cutoff=b['fit_cutoff'])
    with pytest.raises(FitFailure):
        service.validate_plan(dict(c['calibration'], initial_train_weeks=104))


def test_manual_scores_class_order_sigmoid_gradient_normalization_and_failure(monkeypatch):
    raw = np.array([[1., 2., 3.], [-2., 4., 0.]])
    np.testing.assert_array_equal(decision_columns(raw, [2, 0, 1], 3), raw[:, [1, 2, 0]])
    np.testing.assert_array_equal(decision_columns(np.array([2., -1.]), [1, 0], 2), [[2., -2.], [-1., 1.]])
    with pytest.raises(FitFailure): decision_columns(raw[:, :2], [0, 2], 3)
    x, y, theta = np.array([-2., 0., 4.]), np.array([.1, .8, .8]), np.array([.4, -.2])
    value, grad = sigmoid_objective(theta, x, y)
    for j in range(2):
        step = np.eye(2)[j] * 1e-6
        numeric = (sigmoid_objective(theta + step, x, y)[0] - sigmoid_objective(theta - step, x, y)[0]) / 2e-6
        assert grad[j] == pytest.approx(numeric, rel=1e-6)
    assert np.isfinite(value)
    cal = TimeSigmoid(svm_config()['calibration'])
    cal.parameters_ = [dict(class_id=j, slope=1., intercept=0., scale=1.) for j in range(3)]
    p = cal.predict_proba(np.array([[1e300, -1e300, 0.], [-1e300] * 3]))
    assert np.isfinite(p).all() and (p > 0).all()
    np.testing.assert_allclose(p.sum(axis=1), 1., atol=1e-15)
    with pytest.raises(AssertionError, match='forbidden'):
        cal.optimize(np.zeros(6), np.zeros(6), np.zeros(2))
    monkeypatch.setattr(TimeSigmoid, 'optimize', lambda *args: SimpleNamespace(x=np.zeros(2), fun=1., jac=np.zeros(2), success=False, nit=1, status=1, message='STUB_FAIL'))
    with pytest.raises(FitFailure, match='did not converge'):
        cal.fit(np.tile(raw, (3, 1)), np.array([0, 1, 2, 0, 1, 2]), [0, 1, 2])
    assert not hasattr(cal, 'parameters_')


@pytest.mark.parametrize('task', ['classification', 'regression'])
def test_svm_nonlearning_fit_predict_save_load_versions_and_original_units(store, stubs, tmp_path, task):
    train = ds(store, task)
    pre, target, model = model_for(train)
    model.fit(transform_inputs(pre, train), target.transform(train.y), fit_context(train))
    pred = ds(store, task, role='prediction')
    ctx = prediction_context(pred, model.preprocessor, target, model_id='rbf_svm', model_version=model.model_version_)
    X = transform_inputs(model.preprocessor, pred)
    out = model.predict(X, ctx)
    if task == 'classification':
        p = out.filter(like='predicted_state_prob_').to_numpy()
        np.testing.assert_array_equal(out.predicted_state_id, p.argmax(axis=1))
        count = sum(b['status'] == 'ACCEPTED' for b in model.calibration_plan_)
        assert len(stubs) == count + 1
        assert len([d for d in model.diagnostics_ if d['component'] == 'calibrator']) == 3
        assert all(pd.Timestamp(b['latest_train_label']) <= pd.Timestamp(b['fit_cutoff']) for b in model.calibration_plan_ if b['status'] == 'ACCEPTED')
    else:
        assert len(stubs) == 7 and len(model.estimators_) == 7
        np.testing.assert_allclose(out[['predicted_' + c for c in CORE]], np.tile(target.parameters_['center'], (len(pred.keys), 1)))
    model.save(tmp_path / 'model')
    assert not (tmp_path / 'model/coefficients.csv').exists()
    loaded = RBFSVMAdapter.load(tmp_path / 'model')
    pd.testing.assert_frame_equal(out, loaded.predict(X, ctx))
    with pytest.raises(ValueError): loaded.predict(X, replace(ctx, model_id='elastic_net'))
    manifest_path = tmp_path / 'model/manifest.json'
    original = read_json(manifest_path)
    changed = deepcopy(original); changed.pop('content_hash'); changed['library_versions']['scipy'] = 'wrong'; changed['content_hash'] = digest(changed)
    atomic_json(manifest_path, changed)
    with pytest.raises(ValueError, match='versions differ'): RBFSVMAdapter.load(tmp_path / 'model')
    atomic_json(manifest_path, original)
    (tmp_path / 'model/calibrator.json').write_text('{}')
    with pytest.raises(ValueError, match='component modified'): RBFSVMAdapter.load(tmp_path / 'model')


def test_svr_constant_tiny_targets_bounds_and_gamma_training_only(store, stubs):
    train = ds(store, 'regression')
    y = train.y.copy(); y['amihud'] = 1e-30; y['turnover'] = 2.
    train = replace(train, y=y)
    pre, target, model = model_for(train)
    X = transform_inputs(pre, train)
    model.fit(X, target.transform(y), fit_context(train))
    assert len(model.estimators_) == 7
    restored = target.inverse_transform(np.zeros((2, 7)))
    assert (restored.amihud == 1e-30).all() and (restored.turnover == 2.).all()
    assert relative_gamma(X, 10.) == pytest.approx(10. / (X.shape[1] * X.to_numpy().var()))
    assert relative_gamma(np.zeros((2, 4)), 10.) == 10.
    pred = ds(store, 'regression', role='prediction')
    ctx = prediction_context(pred, pre, target, model_id='rbf_svm', model_version=model.model_version_)
    from scripts.market_state.model_contract import regression_output
    invalid = pd.DataFrame(np.tile([-2., -1., 2., -1e-20, -2., 2., 3.], (len(pred.keys), 1)), columns=CORE)
    out = regression_output(ctx, invalid, target.schema_)
    assert out.economic_bound_violations.ne('[]').all()
    np.testing.assert_array_equal(out.predicted_return, invalid['return'])


@pytest.mark.parametrize('mode,expected', [('convergence', 2), ('numeric', 1)])
def test_svm_solver_failure_retry_invalidates_weights(store, stubs, monkeypatch, mode, expected):
    train = ds(store, 'regression'); pre, target, model = model_for(train)
    X, y, ctx = transform_inputs(pre, train), target.transform(train.y), fit_context(train)
    model.fit(X, y, ctx)
    monkeypatch.setattr(RBFSVMAdapter, 'estimator', lambda self, maximum, gamma: KernelStub(False, gamma, mode))
    with pytest.raises(FitFailure) as error: model.fit(X, y, ctx)
    assert len(error.value.diagnostics) == expected
    assert not hasattr(model, 'model_version_')


def test_plan_expands_all_real_component_counts_without_fitting(store):
    c = svm_config(); plan = preview(c, store, 'full')
    assert plan['selected_configurations'] == 112 and plan['core_configurations'] == 16
    assert len(plan['candidate_monthly_tasks']) == 4 * 2 * 2 * 48 * 12
    assert len(plan['calibration_plans']) == 4 * 83
    cls, reg = plan['budgets']
    assert cls['calibration_fits'] > 0 and cls['internal_svc_fit_calls_upper'] > cls['final_svc_fit_calls_upper']
    assert cls['estimator_fit_calls_upper'] == sum(b['internal_svc_fits_upper'] + b['final_svc_fits_upper'] for b in plan['calibration_fit_expansion'])
    assert cls['calibration_fits'] == sum(b['sigmoid_fits_upper'] for b in plan['calibration_fit_expansion'])
    assert reg['calibration_fits'] == 0 and reg['svr_fit_calls_upper'] == reg['estimator_fit_calls_upper']
    assert plan['supervised_fit_calls'] == 0


def test_svm_stub_full_pipeline_automatic_lock_test_and_reports(store, stubs, tmp_path):
    c = svm_config()
    c.update(purpose='ARTIFICIAL_TEST_ONLY', output_root=str(tmp_path), markets=['000985.SH'])
    c['search'].update(candidate_count=2, finalists=1)
    c['resources'].update(cpu_workers=1, minimum_free_gb=0, max_run_gb=1)
    c['statistics']['repetitions'] = 10
    executor = MonthlyExecutor(c, store, versions(c, store))
    pipeline = Pipeline(c, store, run_id='svm-stub', resume=True, artificial=True,
        executor=executor, preflight_function=lambda *args: dict(environment={'purpose': 'ARTIFICIAL_TEST_ONLY'},
            fixed_scales=executor.scales, risk_definition=executor.risk),
        schedule=(['2020-01', '2020-02'], ['2023-01']))
    root = pipeline.run(execute=True)
    assert read_json(root / 'manifest.json')['state'] == 'EXPERIMENT_COMPLETE'
    lock = read_json(root / 'selection.lock.json')
    assert lock['model_rules']['calibration'] == c['calibration']
    assert lock['seeds'] == {'classification': [3060], 'regression': [3060]}
    for name in ['core_classification', 'core_regression', 'macro_increment', 'macro_groups', 'warning_value', 'runtime_quality', 'coverage_status']:
        assert (root / 'tables' / (name + '.csv')).exists()
    quality = pd.read_csv(root / 'tables/runtime_quality.csv')
    assert quality.calibration_fit_calls.sum() > 0
    assert all(not (p.parent / 'coefficients.csv').exists() for p in (root / 'test/fits').glob('*/kernel_diagnostics.json'))
    assert 'RBF-SVM records kernel scale' in (root / 'report.md').read_text(encoding='utf8')
    assert 'ARTIFICIAL_TEST_ONLY' in (root / 'report.md').read_text(encoding='utf8')
    count = len(stubs)
    pipeline.run(execute=True)
    assert len(stubs) == count
