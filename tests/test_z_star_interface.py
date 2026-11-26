"""The sealed Z* release uses the same market rows, targets and training boundary."""
import json
import shutil

import pandas as pd
import pytest

from scripts.market_state.common import MARKETS, OUT
from scripts.market_state.framework import DataStore, information_view, load_dataset
from scripts.market_state.model_contract import (
    fit_inputs, restrict_inputs, training_partition, transform_inputs, validate_pair,
)
from scripts.market_state.z_star_release import DIRECTORY, ENHANCED, EXTENSION, validate_extension


@pytest.fixture(scope='module')
def extended_store():
    return DataStore(feature_extension=EXTENSION)


def test_same_cohorts_and_fixed_financial_inputs(extended_store):
    original = DataStore()
    assert original.data_version == extended_store.data_version
    assert original.spec['feature_version'] != extended_store.spec['feature_version']
    for market in MARKETS:
        args = dict(market_id=market, fold_id='2020-01', task='regression', store=extended_store)
        base = load_dataset(**args, role='train', information_set='M')
        historical = load_dataset(**args, role='train', information_set='M+Z')
        enhanced = load_dataset(**args, role='train', information_set=ENHANCED)
        pure = load_dataset(**args, role='train', information_set='Z_star')
        for counterpart in (historical, enhanced, pure):
            validate_pair(base, counterpart)
        pd.testing.assert_frame_equal(base.X, enhanced.X_market)
        pd.testing.assert_frame_equal(historical.X_market, enhanced.X_market)
        pd.testing.assert_frame_equal(pure.X, enhanced.X_macro)
        assert pure.X_market.empty and pure.X_interactions is None
        for feature in extended_store.spec['z_star_interactions']:
            expected = enhanced.X[feature['macro_feature']] * enhanced.X[feature['market_feature']]
            assert enhanced.X_interactions[feature['feature']].equals(expected)
        pd.testing.assert_frame_equal(
            base.X, load_dataset(**{**args, 'store': original}, role='train', information_set='M').X)
        pd.testing.assert_frame_equal(
            historical.X, load_dataset(**{**args, 'store': original}, role='train', information_set='M+Z').X)

        for group, columns in extended_store.spec['z_star_groups'].items():
            only_group = information_view(enhanced, ENHANCED + '_' + group, store=extended_store)
            without_group = information_view(enhanced, ENHANCED + '_without_' + group, store=extended_store)
            assert set(only_group.X) == set(base.X) | set(columns)
            assert list(without_group.X) == [c for c in enhanced.X if c not in columns]
            validate_pair(enhanced, only_group)
            validate_pair(enhanced, without_group)


def test_z_star_uses_shared_training_and_no_truth_prediction(extended_store, monkeypatch):
    args = dict(market_id='000985.SH', fold_id='2026-11', task='regression', store=extended_store)
    train = load_dataset(**args, role='train', information_set=ENHANCED)
    pre = fit_inputs(train)
    base_train = information_view(train, 'M', store=extended_store)
    purged = training_partition(train, train.keys.iloc[:20], role='train',
                                fit_cutoff=train.metadata.fit_cutoff.iloc[0])
    assert purged.X_interactions.equals(train.X_interactions.iloc[:20])
    original_get = extended_store.get

    def historical_only(name):
        assert name not in {'supervised_targets', 'sample_manifest'}
        return original_get(name)

    monkeypatch.setattr(extended_store, 'get', historical_only)
    pred = load_dataset(**args, role='prediction', information_set=ENHANCED)
    assert pred.y is None and len(pred.X) == 2
    base_pred = load_dataset(**args, role='prediction', information_set='M')
    validate_pair(base_pred, pred)
    pd.testing.assert_frame_equal(base_pred.X, pred.X_market)
    pd.testing.assert_frame_equal(
        transform_inputs(fit_inputs(base_train), base_pred),
        transform_inputs(restrict_inputs(pre, base_train), base_pred),
    )
    with pytest.raises(ValueError, match='only released'):
        load_dataset(**args, role='prediction', information_set=ENHANCED, quality='strict')


def test_z_star_manifest_hashes_are_checked(tmp_path):
    directory = OUT / DIRECTORY
    shutil.copytree(directory, tmp_path / DIRECTORY)
    shutil.copy2(OUT / 'release/seal.json', tmp_path / 'release/seal.json')
    assert validate_extension(tmp_path) == validate_extension(OUT)
    path = tmp_path / DIRECTORY / 'feature_sets.json'
    definitions = json.loads(path.read_text(encoding='utf8'))
    definitions['sets'][ENHANCED].pop()
    path.write_text(json.dumps(definitions), encoding='utf8')
    with pytest.raises(RuntimeError, match='sealed product changed'):
        validate_extension(tmp_path)
