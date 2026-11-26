"""Versioned Z* feature release extending, but not replacing, the sealed snapshot."""
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from .common import KEY, OUT, digest, write
from .release import assert_sealed_products, file_hash

EXTENSION = 'z_star'
ENHANCED = 'M+Z_star'
CORE_INFORMATION_SETS = ('M', 'M+Z', ENHANCED)
QUALITY = 'historical_reconstructed'
DIRECTORY = 'release/z_star'
FORMAT = 'mlec-macro-z-star-release-v1'
PRODUCTS = ('features.parquet', 'feature_catalog.json', 'lineage.parquet',
            'quality_report.json', 'feature_sets.json')
INTERACTION_PARENTS = (
    ('credit_amihud', 'macro__m2_yoy__release_trend3', 'market__amihud_20d',
     'Credit momentum conditional on market price impact'),
    ('funding_volatility', 'macro__dr007__change_20obs', 'market__volatility_20d',
     'Changes in financing costs conditional on market volatility'),
    ('growth_trend', 'macro__pmi_mfg__release_trend3', 'market__return_20d',
     'Growth momentum conditional on the recent market trend'),
    ('currency_correlation', 'macro__usdcny_fixing__change_20obs', 'market__correlation_20d',
     'Currency pressure conditional on market co-movement'),
    ('inflation_drawdown', 'macro__cpi_yoy__new_innovation', 'market__drawdown_20d',
     'New inflation information conditional on a recent market drawdown'),
)
GROUPS = ('growth', 'prices', 'credit', 'rates', 'external')


def is_enhanced(info):
    return info == 'Z_star' or info == ENHANCED or info.startswith(ENHANCED + '_')


def _identity(record):
    return digest({k: v for k, v in record.items() if k != 'feature_version'})[:20]


def validate_extension(data_root):
    root = Path(data_root)
    directory = root / DIRECTORY
    path = directory / 'manifest.json'
    if not path.is_file():
        raise RuntimeError('Z* release missing; run python -m scripts.market_state.run build-z-star')
    record = json.loads(path.read_text(encoding='utf8'))
    if (record.get('format') != FORMAT or record.get('quality') != QUALITY
            or record.get('feature_version') != _identity(record)
            or record.get('base_seal_hash') != file_hash(root / 'release/seal.json')
            or set(record.get('products', {})) != set(PRODUCTS)):
        raise RuntimeError('Z* manifest or base snapshot identity mismatch')
    for name, expected in record['products'].items():
        path = directory / name
        if not path.is_file() or file_hash(path) != expected:
            raise RuntimeError('Z* sealed product changed: ' + name)
    return record


def _extension_definitions(base, catalog):
    features = catalog['features']
    by_feature = {row['feature']: row for row in features}
    if (len(by_feature) != len(features) or not features
            or any(not c.startswith('macro__') for c in by_feature)
            or any(row['group'] not in GROUPS for row in features)):
        raise ValueError('Invalid Z* feature catalog')
    groups = {g: [c for c, row in by_feature.items() if row['group'] == g] for g in GROUPS}
    interactions = []
    for name, macro, market, meaning in INTERACTION_PARENTS:
        if macro not in by_feature or market not in base['sets']['M']:
            raise ValueError(f'Unavailable interaction parents for {name}: {macro}, {market}')
        feature = 'interaction__' + name
        group = by_feature[macro]['group']
        groups[group].append(feature)
        interactions.append(dict(feature=feature, group=group, macro_feature=macro,
            market_feature=market, meaning=meaning, formula=f'{macro} * {market}',
            parents=[dict(dataset=DIRECTORY + '/features.parquet', field=macro),
                     dict(dataset='market_features.parquet', field=market)],
            frequency='weekly', availability='Both parents as of the same weekly prediction cutoff.',
            missing='Missing if either parent is missing. Imputation is fitted in the training fold.'))
    def definitions(market_columns):
        components = [*by_feature, *(row['feature'] for row in interactions)]
        sets = {ENHANCED: market_columns + components, 'Z_star': list(by_feature)}
        for group, columns in groups.items():
            sets[ENHANCED + '_' + group] = market_columns + [c for c in components if c in columns]
            sets[ENHANCED + '_without_' + group] = market_columns + [c for c in components if c not in columns]
        return sets

    return dict(sets=definitions(base['sets']['M']),
                by_market={market: definitions(sets['M']) for market, sets in base['by_market'].items()},
                groups=groups, interactions=interactions)


def _validate_weekly_products(features, lineage, market, macro_columns):
    dates = pd.Index(market.asof_date.unique())
    if (features.asof_date.duplicated().any() or features.asof_date.isna().any()
            or len(features) != len(dates) or not dates.isin(features.asof_date).all()
            or list(features.columns) != ['asof_date', *macro_columns]):
        raise ValueError('Z* must cover the complete weekly anchor set in catalog order')
    cutoff = lineage.asof_date.dt.tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
    if (not lineage.asof_date.isin(dates).all() or not lineage.asof_time.eq(cutoff).all()
            or lineage.available_at.gt(lineage.asof_time).any()
            or not lineage.feature.isin(macro_columns).all()
            or len(lineage) != len(dates) * len(macro_columns)
            or lineage.duplicated(['asof_date','feature']).any()
            or lineage.loc[lineage.status.eq('AVAILABLE'),'available_at'].isna().any()):
        raise ValueError('Invalid Z* point-in-time lineage')
    if np.isinf(features[macro_columns].to_numpy(float)).any():
        raise ValueError('Infinite Z* input')


def assemble_extension(market, features, interactions):
    result = market.merge(features, on='asof_date', how='left', validate='many_to_one', indicator=True)
    if not result._merge.eq('both').all() or not result[KEY].equals(market[KEY].reset_index(drop=True)):
        raise ValueError('Z* assembly changed the market cohort')
    result = result.drop(columns='_merge')
    # Both parents are already keyed to this prediction anchor. No estimated weights.
    products = {row['feature']: result[row['macro_feature']] * result[row['market_feature']]
                for row in interactions}
    return result.assign(**products)


def build_extension(*, data_root=None):
    from .z_star import build_z_star, source_paths

    root = Path(data_root).resolve() if data_root is not None else OUT
    base_version = assert_sealed_products(data_root=root)
    seal_path = root / 'release/seal.json'
    seal_hash = file_hash(seal_path)
    seal = json.loads(seal_path.read_text(encoding='utf8'))
    sources = {
        ('data/market_state/' + path.relative_to(root).as_posix() if path.is_relative_to(root)
         else 'data/' + path.relative_to(root.parent).as_posix()): path
        for path in source_paths(root)
    }
    source_hashes = {original: file_hash(path) for original, path in sources.items()}
    for original, actual in source_hashes.items():
        expected = next((s[original] for s in (seal['products'], seal['admissions'],
                        seal['original_input_hashes']) if original in s), None)
        if actual != expected:
            raise RuntimeError('Z* source differs from the pinned base snapshot: ' + original)
    directory = root / DIRECTORY
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.z-star-', dir=directory.parent) as stage:
        stage = Path(stage)
        build_z_star(root, output_dir=stage)
        base = json.loads((root / 'feature_sets.json').read_text(encoding='utf8'))
        catalog = json.loads((stage / 'feature_catalog.json').read_text(encoding='utf8'))
        definitions = _extension_definitions(base, catalog)
        market = pd.read_parquet(root / 'market_features.parquet')
        features = pd.read_parquet(stage / 'features.parquet')
        lineage = pd.read_parquet(stage / 'lineage.parquet')
        _validate_weekly_products(features, lineage, market, definitions['sets']['Z_star'])
        assemble_extension(market, features, definitions['interactions'])
        write(stage / 'feature_sets.json', definitions)
        record = dict(format=FORMAT, quality=QUALITY, base_data_version=base_version,
            base_feature_version=base['feature_version'], base_seal_hash=seal_hash,
            source_hashes=source_hashes, definition_version=catalog['version'],
            products={name: file_hash(stage / name) for name in PRODUCTS})
        record['feature_version'] = _identity(record)
        write(stage / 'manifest.json', record)
        if (assert_sealed_products(data_root=root) != base_version or file_hash(seal_path) != seal_hash
                or any(file_hash(sources[p]) != h for p, h in source_hashes.items())):
            raise RuntimeError('Z* source or base snapshot changed while building')
        directory.mkdir(exist_ok=True)
        for name in (*PRODUCTS, 'manifest.json'):
            # Keep stamps of byte-identical products stable during an exact rebuild.
            target = directory / name
            if not target.is_file() or file_hash(stage / name) != file_hash(target):
                (stage / name).replace(target)
    return validate_extension(root)
