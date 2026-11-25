"""Build the registered 60-trading-day sensitivity release from sealed inputs."""
from copy import deepcopy
import json
from pathlib import Path
from shutil import copyfile

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CORE, KEY, MARKETS, OUT, VERSION, digest, frame, write
from .dictionary import apply_dictionary, fit_transform, model, state_profiles, training_rows, transform
from .framework import monthly_membership, sample_manifest
from .measure import market_membership, measure_record, validity_masks
from .release import assert_sealed_products, code_hash, file_hash
from .tasks import task_matrix


HORIZON = 60
SETS = ('M', 'M+Z')
VIEW_PRODUCTS = ('calendar.parquet', 'missing_policy.json', 'macro/specifications.json') + tuple(
    f'macro/{view}/{name}.parquet'
    for view in ('historical_reconstructed', 'strict', 'latest_at_retrieval')
    for name in ('features', 'lineage')
)


def _stock_returns(dates, imap, stock_cache):
    returns = np.full((len(dates), len(imap)), np.nan)
    dmap = {date: i for i, date in enumerate(dates)}
    source_hashes = {}
    for year in sorted(set(dates.year)):
        path = stock_cache / f'{year}.parquet'
        before = path.stat()
        data = pd.read_parquet(path, columns=['date', 'instrument_id', 'r'])
        di, si = data.date.map(dmap), data.instrument_id.map(imap)
        if (not data.date.dt.year.eq(year).all() or di.isna().any() or si.isna().any()
                or data.duplicated(['date', 'instrument_id']).any()):
            raise ValueError(f'Invalid date or security key in stock partition {year}')
        returns[di.to_numpy(int), si.to_numpy(int)] = data.r.to_numpy(float)
        source_hashes[path.name] = file_hash(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f'Stock partition changed during read {year}')
    return returns, source_hashes


def _outcomes(parent, stock_cache):
    dates = pd.DatetimeIndex(parent.get('calendar').date)
    master = parent.get('security_history')
    weights = parent.get('membership_snapshots')
    imap = {s: i for i, s in enumerate(sorted(master.instrument_id.unique()))}
    aliasmap = master.set_index('ts_code').instrument_id.to_dict()
    active, ordinary = validity_masks(dates, master, imap)
    returns, stock_hashes = _stock_returns(dates, imap, stock_cache)
    original = parent.get('future_window_outcomes').sort_values(KEY).reset_index(drop=True)
    market_daily = parent.get('market_daily')
    prices = parent.get('index_prices')
    replay, derived = [], []
    for market, weekly in original.groupby('market_id', sort=False):
        membership, _ = market_membership(market, dates, weights, imap, aliasmap, active, ordinary)
        daily = market_daily[market_daily.market_id.eq(market)].set_index('date').reindex(dates)
        price = prices[prices.ts_code.eq(market)].set_index('date').close.reindex(dates).to_numpy()
        anchors = dates.get_indexer(weekly.asof_date)
        if (anchors < 0).any() or not np.array_equal(membership.sum(axis=1), daily.members.to_numpy()):
            raise ValueError(f'Calendar or historical membership differs from sealed data for {market}')
        for anchor, row in zip(anchors, weekly.itertuples(index=False)):
            key = dict(market_id=market, asof_date=row.asof_date, asof_time=row.asof_time)
            replay.append(measure_record(dates, price, daily, returns, membership,
                dict(key, horizon=20), anchor, anchor + 20, 'future'))
            derived.append(measure_record(dates, price, daily, returns, membership,
                dict(key, horizon=HORIZON), anchor, anchor + HORIZON, 'future'))
        print('Replayed 20d and built 60d', market, len(weekly), flush=True)
    replay = pd.DataFrame(replay)
    exact = KEY + ['asof_time', 'label_start', 'label_end', 'label_available_at', 'measurement_valid', 'missing_reason']
    for col in exact:
        a, b = replay[col], original[col]
        if not (a.eq(b) | (a.isna() & b.isna())).all():
            raise ValueError(f'20d replay differs from the sealed {col}')
    numerical = CORE + ['correlation_stocks', 'correlation_union_stocks']
    np.testing.assert_allclose(replay[numerical], original[numerical], rtol=1e-12, atol=1e-24, equal_nan=True)
    outcomes = pd.DataFrame(derived)
    anchor = dates.get_indexer(outcomes.asof_date)
    mature = outcomes.label_end.notna().to_numpy()
    if not (np.array_equal(mature, anchor + HORIZON < len(dates))
            and np.array_equal(dates.get_indexer(outcomes.loc[mature, 'label_end']), anchor[mature] + HORIZON)
            and np.array_equal(dates.get_indexer(outcomes.label_start), np.where(anchor + 1 < len(dates), anchor + 1, -1))
            and outcomes.loc[~mature, CORE].isna().all().all()):
        raise ValueError('60d label calendar validation failed')
    return outcomes, dict(rows=len(replay), numerical_fields=numerical, rtol=1e-12, atol=1e-24,
        stock_partition_sha256=stock_hashes)


def _fit_dictionary(outcomes, parent):
    training = training_rows(outcomes)
    if training.empty:
        raise ValueError('No eligible initial 60d labels')
    parameters = fit_transform(training)
    selected = json.loads((parent.root / 'state_dictionary/dictionary.json').read_text(encoding='utf8'))['selected']
    k, covariance = int(selected['k']), selected['covariance']
    matrix = transform(training, parameters)
    with threadpool_limits(limits=1):
        gmm = model(k, covariance).fit(matrix)
    raw = training.assign(component=gmm.predict(matrix)).groupby('component')[CORE].mean()
    order = raw.sort_values(['return', 'volatility']).index.tolist()
    if not gmm.converged_ or len(order) != k:
        raise RuntimeError('60d dictionary failed its fixed-architecture fit')
    fingerprint = digest(training[KEY + CORE].to_dict('records'))
    version = digest(dict(horizon=HORIZON, training=fingerprint, parameters=parameters,
        means=gmm.means_.tolist(), covariances=gmm.covariances_.tolist(), order=order))[:20]
    selection = dict(k=k, covariance=covariance, rule='architecture fixed from the sealed 20d dictionary')
    artifact = dict(gmm=gmm, transform=parameters, order=order, label_version=version, protocol=VERSION,
        selection=selection, horizon=HORIZON)
    metadata = dict(horizon=HORIZON, label_version=version, protocol=VERSION, transform=parameters,
        component_order=order, selected=selection, training_rows=len(training),
        market_counts=training.market_id.value_counts().to_dict(),
        max_label_available_at=training.label_available_at.max(), training_fingerprint=fingerprint)
    return artifact, metadata, training[KEY + ['label_available_at']]


def build_60d(parent, stock_cache, output):
    """Reaccept a derived target horizon without changing formal snapshot products."""
    output, stock_cache = Path(output).resolve(), Path(stock_cache).resolve()
    if any(output.is_relative_to(p) for p in (OUT, parent.root, stock_cache)):
        raise ValueError('The 60d release needs a separate destination')
    if output.exists():
        raise FileExistsError(output)
    parent_seal_path = parent.root / 'release/seal.json'
    parent_sha256 = file_hash(parent_seal_path)
    parent_seal = json.loads(parent_seal_path.read_text(encoding='utf8'))
    outcomes, replay = _outcomes(parent, stock_cache)
    dictionary, dictionary_meta, training_keys = _fit_dictionary(outcomes, parent)
    targets = apply_dictionary(outcomes, dictionary, 'future')
    target_version = digest(dict(dictionary=dictionary['label_version'],
        outcomes=outcomes.sort_values(KEY).to_dict('records'), horizon=HORIZON))[:20]
    targets['target_version'] = target_version
    parent_manifest = parent.get('sample_manifest').set_index(KEY[:2])
    source_index = pd.MultiIndex.from_frame(targets[KEY[:2]])
    history_valid = parent_manifest.history_valid.reindex(source_index)
    if history_valid.isna().any() or len(history_valid) != len(parent_manifest):
        raise ValueError('Horizon sensitivity needs identical as-of keys')
    manifest = sample_manifest(targets, history_valid.to_numpy())
    membership, plans = monthly_membership(manifest, parent.get('calendar').date)
    pd.testing.assert_frame_equal(plans, parent.get('time_splits'), check_dtype=False)
    train = membership[membership.role.eq('train')].merge(
        targets[KEY + ['label_available_at']], on=KEY, validate='many_to_one')
    if not train.label_available_at.le(train.fit_cutoff).all():
        raise ValueError('Immature 60d training label')
    scored = membership[~membership.role.eq('train')].merge(
        targets[KEY + ['label_end']], on=KEY, validate='one_to_one')
    if not scored.loc[scored.role.eq('validation'), 'label_end'].le('2022-12-31').all():
        raise ValueError('A development label extends into the test period')
    features = parent.get('market_features').assign(horizon=HORIZON)
    spec = deepcopy(parent.spec)
    spec['sets'] = {name: spec['sets'][name] for name in SETS}
    spec['by_market'] = {market: {name: sets[name] for name in SETS} for market, sets in spec['by_market'].items()}
    feature_version = digest(dict(parent=spec['feature_version'], horizon=HORIZON, information_sets=spec['sets']))[:20]
    features['feature_version'] = feature_version
    spec.update(feature_version=feature_version, target_version=target_version, label_version=dictionary['label_version'],
        horizon=HORIZON, historical_feature_dictionary_version=parent.spec['label_version'])
    fields = parent.get('field_dictionary').copy()
    target_fields = fields.dataset_id.isin(['future_window_outcomes', 'supervised_targets'])
    fields.loc[target_fields, 'definition'] = fields.loc[target_fields, 'definition'].str.replace(
        r'\bH\s*=\s*20\b', f'H={HORIZON}', regex=True)
    data_tasks = task_matrix(SETS, plans)
    profiles = state_profiles(outcomes, dictionary)

    output.mkdir(parents=True, exist_ok=False)
    for relative in VIEW_PRODUCTS:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        copyfile(parent.root / relative, path)
        if file_hash(path) != parent_seal['products']['data/market_state/' + relative]:
            raise RuntimeError(f'Sealed input changed during copy: {relative}')
    products = dict(market_features=features, future_window_outcomes=outcomes, supervised_targets=targets,
        sample_manifest=manifest, fold_membership=membership, time_splits=parent.get('time_splits'),
        data_tasks=data_tasks, field_dictionary=fields)
    products.update({'state_dictionary/profiles': profiles, 'state_dictionary/training_keys': training_keys})
    for name, df in products.items():
        frame(name, df, data_root=output)
    joblib.dump(dictionary, output / 'state_dictionary/dictionary.joblib')
    write(output / 'state_dictionary/dictionary.json', dictionary_meta)
    write(output / 'feature_sets.json', spec)
    write(output / 'data_task_config.json', dict(version='data-tasks-v1', horizon=HORIZON, markets=list(MARKETS),
        information_sets=list(SETS), targets=data_tasks.task.unique().tolist(), task_count=len(data_tasks)))
    if file_hash(parent_seal_path) != parent_sha256:
        raise RuntimeError('The 20d parent seal changed during the 60d build')
    evidence = dict(status='PASSED', scope='registered 60d sensitivity of the pinned 20d release',
        parent_data_version=parent.data_version, parent_seal_sha256=parent_sha256, replay_20d=replay,
        exact_trading_calendar_offsets=True, same_historical_feature_values=True, unchanged_asof_keys_and_months=True,
        mature_train_rows_only=True, development_labels_end_before_test=True,
        evaluation=scored.groupby(['market_id', 'role']).agg(n=('asof_date', 'size'),
            latest_asof=('asof_date', 'max'), latest_label_end=('label_end', 'max')).reset_index().to_dict('records'))
    write(output / 'release/horizon_acceptance.json', evidence)
    hashes = {'data/market_state/' + p.relative_to(output).as_posix(): file_hash(p)
        for p in sorted(output.rglob('*')) if p.is_file()}
    seal = dict(snapshot_id=parent_seal['snapshot_id'] + '-sensitivity-60td', cutoff=parent_seal['cutoff'],
        products=hashes, code_hash=code_hash(), target_version=target_version, feature_version=feature_version,
        dictionary_version=dictionary['label_version'], missing_policy_version=spec['missing_policy_version'],
        horizon=HORIZON, parent_data_version=parent.data_version, parent_seal_sha256=parent_sha256)
    seal.update(data_version=digest(seal)[:24], status='SEALED_READY_FOR_MODEL_SELECTION', supervised_models_run=0,
        acceptance='release/horizon_acceptance.json')
    write(output / 'release/seal.json', seal)
    assert_sealed_products(data_root=output)
    return seal['data_version']
