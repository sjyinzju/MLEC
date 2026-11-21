"""Analytical optimality and real contract seams; no supervised fitting."""
from types import SimpleNamespace
from dataclasses import replace
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.market_state.preprocessing import FoldPreprocessor
from scripts.market_state.models.elastic_quality import certify_zero_slopes, classification_quality, regression_quality, weight_hash
from scripts.market_state.models.errors import fit_counts
from scripts.market_state.experiments.config import load_config
from scripts.market_state.experiments.runtime import MonthlyExecutor, versions
from scripts.market_state.framework import DataStore, load_dataset
from scripts.market_state.model_contract import fit_inputs, transform_inputs, restrict_inputs


def test_semantic_scale_tiny_positive_iqr_and_units(tmp_path):
    train = pd.DataFrame(dict(current_state_prob_0=[0., 1e-15, 2e-15, 1.],
        current_state_prob_0_lag1w=[0., 1e-15, 2e-15, 1.], binary=[0., 1., 0., 1.],
        value=[1., 2., np.nan, 4.], tiny_unit=[1e-20, 2e-20, 3e-20, 4e-20],
        near=[1., 1.+2e-16, 1., 1.], constant=[2.]*4, empty=[np.nan]*4,
        current_state_id=[0., 1., 0., np.nan]))
    p = FoldPreprocessor().fit(train)
    names = list(p.get_feature_names_out())
    a = p.transform(train)
    for col in ['current_state_prob_0', 'current_state_prob_0_lag1w', 'binary']:
        np.testing.assert_array_equal(a[:, names.index(col)], train[col])
    assert 'near' not in names and 'constant' not in names and 'empty' not in names
    assert p.scale_['tiny_unit'] < 1e-19
    assert a[:, names.index('value')].mean() == pytest.approx(0., abs=1e-15)
    assert a[:, names.index('value')].std() == pytest.approx(1.)
    assert a[2, names.index('missing__value')] == 1.
    before = p.schema_.copy()
    future = train.copy(); future['value'] = [1e9]*4
    assert p.transform(future)[:, names.index('value')].max() > 1e8
    assert p.schema_ == before  # no future fit or clipping
    p.save(tmp_path)
    q = FoldPreprocessor.load(tmp_path)
    np.testing.assert_array_equal(p.transform(future), q.transform(future))
    q.scale_.iloc[0] = 2.
    joblib.dump(q, tmp_path/'preprocessor.joblib')
    with pytest.raises(ValueError, match='statistics modified'):
        FoldPreprocessor.load(tmp_path)
    for value in [np.inf, -.01, 1.01]:
        bad = train.copy(); bad.loc[0, 'current_state_prob_0'] = value
        with pytest.raises(ValueError): p.transform(bad)


def test_binary_missing_uses_train_mode_and_nominal_infinity_is_rejected():
    x = pd.DataFrame(dict(binary=[0., 1., np.nan, np.nan], current_state_id=[0., 1., 0., np.nan]))
    pre = FoldPreprocessor().fit(x)
    out = pre.transform(x)
    names = pre.get_feature_names_out().tolist()
    np.testing.assert_array_equal(out[:, names.index('binary')], [0., 1., 0., 0.])
    np.testing.assert_array_equal(out[:, names.index('missing__binary')], [0., 0., 1., 1.])
    bad = x.copy(); bad.loc[0, 'current_state_id'] = np.inf
    with pytest.raises(ValueError, match='nominal'): pre.transform(bad)


@pytest.mark.parametrize('binary', [False, True])
@pytest.mark.parametrize('balanced', [False, True])
def test_intercept_feasible_optimum_and_false_success(binary, balanced):
    y = np.array([0]*5 + [1]*90 + ([] if binary else [2]*5))
    classes = np.unique(y)
    frequencies = np.bincount(y)/len(y)
    if balanced: frequencies = np.full(len(classes), 1./len(classes))
    x = np.zeros((len(y), 2))
    b = np.array([np.log(frequencies[1]/frequencies[0])]) if binary else np.log(frequencies)
    e = SimpleNamespace(classes_=classes, coef_=np.zeros((len(b), 2)), intercept_=b)
    p = dict(C=.0001, l1_ratio=.95, tol=1e-4)
    good = classification_quality(e, x, y, p, 'balanced' if balanced else None)
    assert good['accepted'] and good['max_intercept_residual'] < 1e-14
    e.intercept_ = b + np.arange(len(b)) if not binary else b + 1.
    assert not classification_quality(e, x, y, p, 'balanced' if balanced else None)['accepted']
    if not balanced:
        e.intercept_ = np.zeros_like(b)
        assert not classification_quality(e, x, y, p)['accepted']


@pytest.mark.parametrize('labels', [[0, 2], [0, 1, 2]])
def test_zero_slopes_require_exact_subgradient_bound(labels):
    from sklearn.linear_model import LogisticRegression
    y = np.repeat(labels, np.arange(1, len(labels) + 1))
    X = pd.DataFrame({'predictive': (y == labels[-1]).astype(float)})
    model = LogisticRegression(solver='saga', l1_ratio=.5)
    p = dict(C=1e-4, l1_ratio=.5, tol=1e-4)
    certificate = certify_zero_slopes(model, X, y, p, None)
    assert certificate['kkt_max'] == 0. and model.n_iter_[0] == 0
    np.testing.assert_array_equal(model.classes_, labels)
    expected = np.unique(y, return_counts=True)[1] / len(y)
    np.testing.assert_allclose(model.predict_proba(X), np.tile(expected, (len(y), 1)))
    # A zero solution can fit within the iterative solver slack while still
    # violating the exact subgradient inequality.
    p['C'] = p['l1_ratio'] / ((certificate['max_smooth_gradient'] - 1e-6) * len(y))
    assert classification_quality(model, X, y, p)['accepted']
    assert certify_zero_slopes(model, X, y, p, None) is None
    assert fit_counts([{'estimator_fit_called': False}, {}, {'component': 'calibrator'}]) == {
        'estimator_fit_calls': 1, 'calibration_fit_calls': 1}


@pytest.mark.parametrize('ratio', [.05, .95, 1.])
def test_regression_independent_primal_dual_rejects_false_zero_gap(ratio):
    x = np.array([-2., -1., 1., 2.])[:, None]
    y = 2.*x[:, 0] + 3.
    alpha = .1
    w = (np.mean(x[:, 0]*(y-y.mean()))-alpha*ratio)/(np.mean(x*x)+alpha*(1-ratio))
    e = SimpleNamespace(coef_=np.array([w]), intercept_=3., dual_gap_=0.)
    p = dict(alpha=alpha, l1_ratio=ratio, tol=1e-4)
    assert regression_quality(e, x, y, p)['accepted']
    e.coef_[:] = 0.
    bad = regression_quality(e, x, y, p)
    assert not bad['accepted'] and bad['independently_computed_dual_gap'] > 0.


def test_stable_weight_identity_survives_numpy_layout_and_pickle(tmp_path):
    a = np.arange(12., dtype=float).reshape(3, 4)
    e = SimpleNamespace(coef_=a[:, :3], intercept_=np.zeros(3), classes_=np.arange(3))
    before = weight_hash([e])
    joblib.dump(e, tmp_path/'weights.joblib')
    q = joblib.load(tmp_path/'weights.joblib')
    assert weight_hash([q]) == before
    q.coef_[0, 0] += 1.
    assert weight_hash([q]) != before


def test_matrix_cache_reuses_views_is_bounded_and_checks_identity():
    s, c = DataStore(), load_config()
    c['resources']['transform_cache_entries'] = 1
    identity = versions(c, s)
    executor = MonthlyExecutor(c, s, identity)
    def task(fold='2020-01', info='M+Z'):
        return dict(identity=dict(market_id='000985.SH', task='classification', fold_id=fold,
            information_set=info, versions=identity))
    first = executor.matrices(task())
    second = executor.matrices(task())
    assert first[-1] is second[-1] and first[-2] is second[-2]
    m = executor.matrices(task(info='M'))
    common = m[-2].columns
    np.testing.assert_array_equal(m[-2], first[-2][common])
    np.testing.assert_array_equal(transform_inputs(fit_inputs(m[0]), m[0]), m[-2])
    bad = task(); bad['identity']['versions'] = dict(identity, data_version='wrong')
    with pytest.raises(ValueError, match='cache task version'): executor.matrices(bad)
    executor.matrices(task(fold='2020-02'))
    assert len(executor.cache) == 1 and executor.cache_stats['matrix_hits'] == 1


def test_training_statistics_do_not_use_prediction_or_y():
    s = DataStore()
    train = load_dataset(market_id='000985.SH', task='classification', information_set='M+Z', fold_id='2020-01', role='train', store=s)
    a = fit_inputs(train)
    changed = replace(train, y=train.y.assign(future_state_id=1))
    b = fit_inputs(changed)
    assert a.schema_ == b.schema_
    prediction = load_dataset(market_id='000985.SH', task='classification', information_set='M+Z', fold_id='2020-01', role='prediction', store=s)
    with pytest.raises(ValueError, match='train'):
        fit_inputs(prediction)


def test_retry_metrics_count_physical_history_without_negative_aliases():
    from scripts.market_state.experiments.reports import retry_counts
    assert retry_counts(dict(attempts=0, diagnostics=[]))['retries'] == 0
    record = dict(attempts=0, attempt_history=[{}, {}], diagnostics=[dict(attempt=1), dict(attempt=2)])
    assert retry_counts(record) == dict(task_attempts=2, task_retries=1, solver_retries=1, retries=2)
    assert retry_counts(dict(attempts=0, attempt_history=[dict(attempt=2)], diagnostics=[]))['task_retries'] == 1


def test_resource_measurement_and_explicit_no_execute_boundary():
    from scripts.market_state.experiments.scheduling import process_usage
    from scripts.market_state.experiments.technical import technical_check
    u = process_usage()
    assert u['pid'] > 0 and u['cpu_seconds'] >= 0 and u['peak_rss_bytes'] > 0
    assert technical_check(execute=False) is None


@pytest.mark.parametrize('ratio', [.05, .95, 1.])
def test_augmented_lars_objective_is_exact_elastic_net(ratio):
    from scripts.market_state.models.elastic_net import regression_geometry
    rng = np.random.default_rng(331)
    x, y, w = rng.normal(size=(15, 6)), rng.normal(size=15), rng.normal(size=6)
    alpha = .001
    g = regression_geometry(x, alpha, ratio)
    yc = y-y.mean()
    ya = np.r_[yc, np.zeros(len(g['augmented'])-len(y))]
    mapped = len(y)*alpha*ratio/len(ya)
    lasso = np.mean((ya-g['augmented']@w)**2)/2. + mapped*abs(w).sum()
    original = np.mean((yc-(x-x.mean(axis=0))@w)**2)/2. + alpha*ratio*abs(w).sum() + alpha*(1-ratio)*np.dot(w,w)/2.
    assert lasso*len(ya)/len(y) == pytest.approx(original, rel=1e-13)
    np.testing.assert_allclose(g['gram'],g['augmented'].T@g['augmented'],atol=1e-13)


def test_augmented_lars_mapping_and_intercept_without_real_training(monkeypatch):
    from sklearn.linear_model import LassoLars
    from scripts.market_state.models.elastic_net import AugmentedLarsElasticNet
    x = pd.DataFrame(dict(a=[1.,2.,3.,4.], b=[3.,2.,1.,0.]))
    y = np.array([4.,5.,6.,7.])
    captured = []
    def fake(self, X, y):
        captured.append((self.alpha, len(X), self.fit_intercept))
        self.coef_ = np.array([.5,-.5]);self.n_iter_ = 2
        return self
    monkeypatch.setattr(LassoLars,'fit',fake)
    from scripts.market_state.models import elastic_net as elastic_module
    monkeypatch.setattr(elastic_module,'regression_quality',lambda *args:dict(accepted=True))
    e = AugmentedLarsElasticNet(alpha=.1,l1_ratio=.5).fit(x,y)
    assert captured == [(pytest.approx(4*.1*.5/6),6,False)]
    assert e.predict(x).mean() == pytest.approx(y.mean())
    assert e.solver_mapping_['original_rows'] == 4 and e.solver_mapping_['augmented_rows'] == 6


def test_fenchel_dual_derivatives_and_bound_without_optimization():
    from scripts.market_state.models.elastic_quality import elastic_dual_state
    rng = np.random.default_rng(871)
    x = rng.normal(size=(9,5));x -= x.mean(axis=0)
    y = rng.normal(size=9);y -= y.mean()
    theta = rng.normal(size=9);theta -= theta.mean()
    value, gradient, hessian, w = elastic_dual_state(theta,x,y,.03,.2,hessian=True)
    for j in range(len(theta)):
        direction=np.eye(len(theta))[j]*1e-6
        plus=elastic_dual_state(theta+direction,x,y,.03,.2)
        minus=elastic_dual_state(theta-direction,x,y,.03,.2)
        assert (plus[0]-minus[0])/2e-6 == pytest.approx(gradient[j],rel=1e-6,abs=1e-6)
        np.testing.assert_allclose((plus[1]-minus[1])/2e-6,hessian[:,j],rtol=1e-6,atol=1e-6)
    primal=np.mean((y-x@w)**2)/2. + .03*abs(w).sum()+.2*np.dot(w,w)/2.
    assert primal+value >= 0
    assert primal+value == pytest.approx(np.dot(gradient,gradient)/(2.*len(y)),rel=1e-12)


def test_pure_l1_certificate_checks_feasibility_and_original_objective():
    # Closed-form one-feature Lasso; no solver or optimizer is called.
    x = np.array([-2., -1., 1., 2.])[:, None]
    y, alpha = 2.*x[:, 0]+3., .1
    w = (np.mean(x[:, 0]*(y-y.mean()))-alpha)/np.mean(x*x)
    theta = (y-y.mean()-x[:, 0]*w)/len(y)
    e = SimpleNamespace(coef_=np.array([w]), intercept_=3., dual_gap_=0., dual_certificate_=theta)
    p = dict(alpha=alpha, l1_ratio=1., tol=1e-4)
    good = regression_quality(e, x, y, p)
    assert good['accepted'] and good['dual_certificate_hash']
    assert abs(good['primal_objective']-good['dual_objective']) < 1e-14
    e.coef_ = np.array([0.])
    assert not regression_quality(e, x, y, p)['accepted']
    e.dual_certificate_ = theta*2.
    with pytest.raises(ValueError, match='Infeasible pure L1'):
        regression_quality(e, x, y, p)


def test_pure_l1_lars_internal_broadcast_uses_existing_dual_polish(monkeypatch):
    from scripts.market_state.models import elastic_net
    X = pd.DataFrame({'x': [-1., 0., 1.]})
    y = np.ones(3)
    calls = []

    def broken_path(*args, **kwargs):
        raise ValueError('operands could not be broadcast together with shapes (3,) (2,)')

    def check_initialization(self, geometry, values):
        np.testing.assert_array_equal(self.coef_, [0.])
        np.testing.assert_array_equal(values, y)
        calls.append(geometry['rows'])

    monkeypatch.setattr(elastic_net.LassoLars, 'fit', broken_path)
    monkeypatch.setattr(elastic_net.AugmentedLarsElasticNet, 'polish', check_initialization)
    model = elastic_net.AugmentedLarsElasticNet(alpha=.1, l1_ratio=1.).fit(X, y)
    assert calls == [3]
    assert model.n_iter_ == 0
    assert 'broadcast' in model.solver_mapping_['lars_path_error']
    assert regression_quality(model, X, y, dict(alpha=.1, l1_ratio=1., tol=1e-4))['accepted']
    with pytest.raises(ValueError, match='broadcast'):
        elastic_net.AugmentedLarsElasticNet(alpha=.1, l1_ratio=.95).fit(X, y)
