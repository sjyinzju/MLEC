"""Forest contract tests use non-learning stubs; actual fits run in technical acceptance."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from scripts.market_state.common import CORE
from scripts.market_state.experiments.forest_acceptance import PARAMETERS, POLICY, SEED, synthetic_data
from scripts.market_state.model_contract import fit_context, fit_inputs, prediction_context, transform_inputs
from scripts.market_state.models import create_model
from scripts.market_state.models.errors import FitFailure
from scripts.market_state.target_adapters import fit_targets


def configured(task, train, policy=POLICY, **extra):
    parameters = dict(PARAMETERS, **extra)
    if task == 'classification':
        parameters['class_weight'] = 'balanced'
    pre, target = fit_inputs(train), fit_targets(train)
    return create_model('random_forest', task=task, preprocessor=pre, target_adapter=target,
        training_keys=train.keys, parameters=parameters, seed=SEED, policy=policy)


def forecast(model, task):
    future = synthetic_data(task, '2020-01', 'prediction', 'informed')
    Xp = transform_inputs(model.preprocessor, future)
    ctx = prediction_context(future, model.preprocessor, model.target_adapter, model_id='random_forest',
                             model_version=model.model_version_, input_matrix=Xp)
    return model.predict(Xp, ctx)


def test_probability_order_and_missing_training_class(monkeypatch):
    task = 'classification'
    train = synthetic_data(task, '2020-01', 'train', 'informed')
    train = replace(train, y=train.y.replace({1: 0}))

    def fit_stub(estimator, X, y):
        assert y.ndim == 1
        assert set(y) == {0, 2}
        estimator.classes_ = np.array([2, 0])
        estimator.estimators_ = []

    monkeypatch.setattr(RandomForestClassifier, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestClassifier, 'predict_proba',
                        lambda self, X: np.tile([.7, .3], (len(X), 1)))
    model = configured(task, train)
    X, y = transform_inputs(model.preprocessor, train), model.target_adapter.transform(train.y)
    model.fit(X, y, fit_context(train))
    out = forecast(model, task)
    np.testing.assert_array_equal(out.predicted_state_prob_0, .3)
    np.testing.assert_array_equal(out.predicted_state_prob_1, 0.)
    np.testing.assert_array_equal(out.predicted_state_prob_2, .7)
    assert out.predicted_state_id.eq(2).all()
    assert len(model.diagnostics_) == 1
    fitting_version, native_prediction_version = model.forest_weights_version_, model.model_version_
    model.set_probability_alpha(.1)
    stable = forecast(model, task)
    expected = (train.y.future_state_id.value_counts().reindex([0, 1, 2], fill_value=0).to_numpy() + 1) / (len(train.y) + 3)
    np.testing.assert_allclose(stable.filter(like='predicted_state_prob').to_numpy(),
                               np.tile(.9 * np.array([.3, 0., .7]) + .1 * expected, (len(stable), 1)))
    assert stable.predicted_state_prob_1.gt(0).all()
    assert model.forest_weights_version_ == fitting_version and model.model_version_ != native_prediction_version
    strict = configured(task, train, dict(POLICY, missing_class='error'))
    with pytest.raises(FitFailure, match='Insufficient training classes'):
        strict.fit(X, y, fit_context(train))


@pytest.mark.parametrize('architecture', ['native', 'independent'])
def test_forest_regression_fit_and_seven_target_units(monkeypatch, architecture):
    task = 'regression'
    train = synthetic_data(task, '2020-01', 'train', 'informed')
    model = configured(task, train, regression_architecture=architecture)
    adapted = model.target_adapter.transform(train.y)
    output_vector = np.linspace(-.1, .1, len(CORE))
    calls = []

    def fit_stub(estimator, X, y):
        j = len(calls)
        calls.append((estimator.n_jobs, estimator.max_features, estimator.max_samples))
        np.testing.assert_array_equal(y, adapted if architecture == 'native' else adapted[:, j])
        estimator.test_value = output_vector if architecture == 'native' else output_vector[j]
        estimator.estimators_ = []

    monkeypatch.setattr(RandomForestRegressor, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestRegressor, 'predict', lambda self, X: np.repeat(
        np.asarray(self.test_value)[None, ...], len(X), axis=0))
    model.fit(transform_inputs(model.preprocessor, train), adapted, fit_context(train))
    result = forecast(model, task)
    expected = model.target_adapter.inverse_transform(np.tile(output_vector, (len(result), 1)))
    pd.testing.assert_frame_equal(result[['predicted_' + c for c in CORE]].set_axis(CORE, axis=1), expected)
    assert calls == [(1, 1., 1.)] * (7 if architecture == 'independent' else 1)
    assert result.output_units.eq('original').all()



def test_rotation_preserves_mixed_macro_types(monkeypatch):
    from types import SimpleNamespace
    from scripts.market_state.common import KEY
    from scripts.market_state.experiments import forest_diagnostics as diagnostics
    from scripts.market_state.framework import DataStore, load_dataset

    store = DataStore(feature_extension='z_star')
    pred = load_dataset(market_id='000985.SH', information_set='M+Z', task='classification',
                        fold_id='2020-03', role='prediction', store=store)
    assert pred.X_macro.dtypes.nunique() > 1
    score = pred.keys.assign(loss=0.1, brier=0.02)
    lineage = {col: group for group, columns in store.spec['groups'].items() for col in columns}
    stub = SimpleNamespace(task='classification', macro_lineage=lineage, preprocessor=None,
                           predict=lambda X, context: None)

    def transform(_, shifted):
        assert shifted.X.dtypes.equals(pred.X.dtypes)
        assert shifted.X_macro.dtypes.equals(pred.X_macro.dtypes)
        return shifted.X

    monkeypatch.setattr(diagnostics, 'transform_inputs', transform)
    monkeypatch.setattr(diagnostics, 'score_predictions', lambda *a, **k: score)
    actual = diagnostics.forest_perturbation_losses(stub, pred, None, None, score, fixed_scale=None, interactions=[])
    assert 'all_macro' in set(actual.group)
    assert set(actual[KEY].itertuples(index=False, name=None)) == set(pred.keys.itertuples(index=False, name=None))
    assert (actual.source_asof_date != actual.asof_date).all()
