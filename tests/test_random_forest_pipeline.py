"""Artificial forest orchestration checks with no supervised learning."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from scripts.market_state.common import CORE, ROOT
from scripts.market_state.experiments import forest_diagnostics, reports
from scripts.market_state.experiments.artifacts import read_json
from scripts.market_state.experiments.config import RF_INFORMATION, data_store, load_config
from scripts.market_state.experiments.pipeline import Pipeline, group_id
from scripts.market_state.experiments.runtime import MonthlyExecutor, preview, versions
from scripts.market_state.models.random_forest import RandomForestAdapter


def test_forest_three_way_search_lock_and_paired_test(tmp_path, monkeypatch):
    config = load_config(ROOT / 'config/experiments/random_forest.yaml')
    store = data_store(config)
    plan = preview(config, store, 'core')
    grid = pd.DataFrame(plan['candidate_monthly_tasks'])
    for _, rows in grid.groupby(['market_id', 'task', 'candidate_id']):
        assert set(rows.information_set) == set(RF_INFORMATION)
        assert rows.groupby('information_set').fold_id.nunique().eq(36).all()
    assert all(row['seeds'] == [3060, 3061, 3062] for row in plan['configurations'])

    config.update(purpose='ARTIFICIAL_TEST_ONLY', output_root=str(tmp_path), markets=['000985.SH'])
    config['search'].update(candidate_count=2, profiles=config['search']['profiles'][:1],
                            feature_fractions=[.35, 1.], stability_seeds=[3060])
    config['resources'].update(minimum_free_gb=0, max_run_gb=1, cpu_workers=1)
    config['statistics']['repetitions'] = 10

    def fit_stub(estimator, X, y):
        estimator.estimators_ = []
        if isinstance(estimator, RandomForestClassifier):
            estimator.classes_ = np.unique(y)
            enhanced = any('interaction__' in name for name in X)
            estimator.preferred_ = estimator.max_features == (1. if enhanced else .35)

    def predict_stub(estimator, X):
        weights = np.where(estimator.classes_ == 1, 4. if estimator.preferred_ else 1., 1.)
        return np.tile(weights / weights.sum(), (len(X), 1))

    monkeypatch.setattr(RandomForestClassifier, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestClassifier, 'predict_proba', predict_stub)
    monkeypatch.setattr(RandomForestRegressor, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestRegressor, 'predict', lambda self, X: np.zeros((len(X), len(CORE))))
    monkeypatch.setattr(RandomForestAdapter, 'save', lambda self, path: path.mkdir())
    monkeypatch.setattr(RandomForestAdapter, 'diagnostic_artifact', lambda self: {})
    monkeypatch.setattr(RandomForestAdapter, 'probability_evidence',
                        lambda self, X, output, *, key_columns: output[key_columns])
    monkeypatch.setattr(forest_diagnostics, 'forest_perturbation_losses', lambda *args, **kwargs: None)
    monkeypatch.setattr(reports, 'figures', lambda *args: None)

    executor = MonthlyExecutor(config, store, versions(config, store))

    def preflight_stub(*args):
        return dict(environment={'purpose': 'ARTIFICIAL_TEST_ONLY'}, fixed_scales=executor.scales,
                    risk_definition=executor.risk)

    development, test = ['2020-01', '2022-12'], ['2023-01']
    runner = Pipeline(config, store, suite='core', run_id='forest-artificial', resume=True,
                      executor=executor, preflight_function=preflight_stub, artificial=True,
                      schedule=(development, test))
    root = runner.run(execute=True)
    manifest = read_json(root / 'manifest.json')
    assert manifest['state'] == 'EXPERIMENT_COMPLETE'
    locked = read_json(root / 'selection.lock.json')
    winners = locked['parameters']
    assert len(winners) == 6
    assert all(row['expected_months'] == development for row in winners.values())
    market, task = '000985.SH', 'classification'
    assert winners[group_id(market, task, 'M')]['parameters'] != winners[group_id(market, task, 'M+Z_star')]['parameters']
    for stage in ('development', 'test'):
        pairs = pd.read_parquet(root / stage / 'losses/paired_differences.parquet')
        expected = {('M', 'M+Z'), ('M+Z', 'M+Z_star'), ('M', 'M+Z_star')}
        for _, rows in pairs.groupby(['task', 'mode', 'metric']):
            assert set(zip(rows.left, rows.right)) == expected
        assignments = read_json(root / stage / 'selection/assignments.json')
        for row in assignments:
            identity = row['identity']
            if identity['family'] != 'random_forest':
                continue
            source = 'M' if identity['mode'] == 'fixed_m_params' else identity['information_set']
            winner = winners[group_id(identity['market_id'], identity['task'], source)]
            assert identity['parameters'] == winner['parameters']
