"""Artificial forest orchestration checks with no supervised learning."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from scripts.market_state.common import CORE, ROOT, KEY
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
    config['search'].update(candidate_count=2, finalists=2, forest_levels=dict(
        n_estimators=[32], max_depth=[3], min_samples_leaf=[4], max_features=[.35, 1.],
        max_samples=[1.], class_weight=[None]))
    config['resources'].update(minimum_free_gb=0, max_run_gb=1, cpu_workers=1)
    config['statistics']['repetitions'] = 10

    def fit_stub(estimator, X, y):
        estimator.estimators_ = []
        if isinstance(estimator, RandomForestClassifier):
            estimator.classes_ = np.unique(y)
            enhanced = any('interaction__' in name for name in X)
            estimator.preferred_ = estimator.max_features == (1. if enhanced else .35)
        else:
            estimator.target_shape_ = y.shape[1:]

    def predict_stub(estimator, X):
        weights = np.where(estimator.classes_ == 1, 4. if estimator.preferred_ else 1., 1.)
        return np.tile(weights / weights.sum(), (len(X), 1))

    monkeypatch.setattr(RandomForestClassifier, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestClassifier, 'predict_proba', predict_stub)
    monkeypatch.setattr(RandomForestRegressor, 'fit', fit_stub)
    monkeypatch.setattr(RandomForestRegressor, 'predict', lambda self, X: np.zeros((len(X), *self.target_shape_)))
    monkeypatch.setattr(RandomForestAdapter, 'diagnostic_artifact', lambda self: {})

    def probability_stub(model, X, output, *, key_columns):
        ids = model.target_adapter.schema_['class_ids']
        selected = ['predicted_state_prob_' + str(c) for c in ids]
        result = output[key_columns + selected].copy()
        result[['native_state_prob_' + str(c) for c in ids]] = model._native_probabilities(X)
        result[['train_history_prob_' + str(c) for c in ids]] = np.broadcast_to(model.training_prior_, (len(X), len(ids)))
        return result.assign(probability_alpha=model.probability_alpha)

    monkeypatch.setattr(RandomForestAdapter, 'probability_evidence', probability_stub)
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
    assert all(set(row['selected_scores_by_seed']) == {'3060', '3061', '3062'} for row in winners.values())
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
            if identity['task'] == 'classification':
                assert identity['parameters']['probability_alpha'] > 0
                directory = root / row['artifact']
                evidence = pd.read_parquet(directory / 'probability_evidence.parquet')
                pd.testing.assert_frame_equal(evidence[KEY], pd.read_parquet(directory / 'predictions.parquet')[KEY])
                if stage == 'development' and identity['mode'] == 'retuned_core':
                    context = read_json(directory / 'context.json')
                    assert context['replayed_forest_fit_id']
                    assert context['estimator_fit_calls'] == 0


def test_forest_export_recovers_missing_receipt_without_rewriting_archive(tmp_path):
    from zipfile import ZipFile
    from scripts.market_state.experiments.artifacts import atomic_json
    from scripts.market_state.experiments.forest_export import export_forest_run
    from scripts.market_state.release import file_hash

    run = tmp_path / 'sample-run'
    lock_path = run / 'selection.lock.json'
    atomic_json(lock_path, {'selection': 'artificial export fixture'})
    lock = file_hash(lock_path)
    ident = dict(run_id='sample-run', purpose='RESEARCH', lock_hash=lock)
    atomic_json(run / 'manifest.json', dict(ident, model='random_forest', versions={'config': 'example'},
                                          development_complete=True, test_complete=True))
    for stage in ('development', 'test'):
        atomic_json(run / stage / 'report_manifest.json', ident)
    atomic_json(run / 'test/fits/example/context.json', {'data': 'included'})
    archive = export_forest_run(run)
    before = file_hash(archive)
    with ZipFile(archive) as z:
        assert z.testzip() is None
        assert 'sample-run/test/fits/example/context.json' in z.namelist()
        assert 'sample-run/.run.lock' not in z.namelist()
    archive.with_suffix('.zip.json').unlink()
    assert export_forest_run(run) == archive and file_hash(archive) == before
    assert read_json(archive.with_suffix('.zip.json'))['sha256'] == before
