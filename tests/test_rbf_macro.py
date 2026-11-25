import numpy as np
import pandas as pd
from scripts.market_state.common import CORE
from scripts.market_state.experiments.config import candidates, load_config
from scripts.market_state.experiments.pipeline import Pipeline
from scripts.market_state.experiments.rbf_acceptance import CONFIG
from scripts.market_state.experiments.rbf_diagnostics import permute_validation
from scripts.market_state.models.rbf_geometry import BlockGeometry


def test_weighted_preserves_financial_geometry_and_missing_flags():
    X = pd.DataFrame({'market__x': [0., 1., 2., 3.], 'market__constant': [1.] * 4,
        'macro__pmi__latest': [2., 10., 15., 7.], 'missing__macro__pmi__latest': [0., 0., 1., 0.],
        'macro__credit__not_applicable': [0., 1., 1., 0.], 'macro__credit__age_days': [4., 3., 2., 0.]})
    lineage = {'macro__pmi__latest': 'growth', 'macro__credit__not_applicable': 'credit',
        'macro__credit__age_days': 'credit', 'macro__absent__latest': 'external'}
    market = X.iloc[:, :2]
    m = BlockGeometry.fit(market, lineage, 'compact', 0.)
    zero = BlockGeometry.fit(X, lineage, 'compact', 0.)
    np.testing.assert_array_equal(m.transform(market), zero.transform(X))
    positive = BlockGeometry.fit(X, lineage, 'compact', .5)
    np.testing.assert_allclose(positive.transform(X).var(0).sum(), 1.5)
    assert positive.state['blocks']['macro']['columns'] == ['macro__pmi__latest',
        'missing__macro__pmi__latest', 'macro__credit__not_applicable']
    shifted = X.copy()
    shifted['macro__pmi__latest'] += 20000.
    np.testing.assert_array_equal(zero.transform(shifted), m.transform(market))


def test_weighted_matrix_coverage_candidate_budgets_and_target_choice():
    config = load_config(CONFIG)
    assert config['search']['coarse_months'] == list(range(1, 13))
    for task in config['tasks']:
        left = candidates(config, task, 'M')
        right = candidates(config, task, 'M+Z')
        assert len(left) == len(right) == 16
        assert {r['candidate_id'] for r in right if r['parameters']['macro_weight'] == 0} <= {r['candidate_id'] for r in left}
        assert len(candidates(config, task, 'M+Z_credit')) == 4
    rows = candidates(config, 'regression', 'M+Z_credit')
    for j, row in enumerate(rows):
        row.update(valid=True, n=150, target_scores={c: float((k + j) % 2) + j / 10 for k, c in enumerate(CORE)})
    winner = object.__new__(Pipeline).weighted_winner(rows, 'regression')
    assert len(set(winner['target_choice_ids'].values())) == 2
    assert len(winner['parameters']['target_parameters']) == len(CORE)


def test_perturbation_keeps_validation_keys_and_joint_two_week_blocks():
    dates = pd.date_range('2022-01-07', periods=5, freq='W-FRI')
    keys = pd.DataFrame(dict(market_id='000985.SH', asof_date=dates, horizon=20))
    X = pd.DataFrame({'market__x': np.arange(5), 'macro__a__latest': np.arange(5),
        'missing__macro__a__latest': np.arange(5) + 100})
    shifted, source = permute_validation(X, keys, {'macro__a__latest': 'growth'}, weeks=2, seed=3059)
    np.testing.assert_array_equal(shifted['market__x'], X['market__x'])
    np.testing.assert_array_equal(shifted['macro__a__latest'], [2, 3, 0, 1, 4])
    np.testing.assert_array_equal(shifted['missing__macro__a__latest'], [102, 103, 100, 101, 104])
    np.testing.assert_array_equal(source.source_asof_date, dates[[2, 3, 0, 1, 4]])
