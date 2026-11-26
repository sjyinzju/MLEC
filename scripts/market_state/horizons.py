"""Build the registered 60-trading-day sensitivity release from sealed inputs."""
from copy import deepcopy
import json
from pathlib import Path
from shutil import copyfile

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CORE, KEY, MARKETS, OUT, ROOT, VERSION, clock, digest, frame, write
from .dictionary import CONFIG, apply_dictionary, dictionary_candidates, fit_transform, model, state_profiles, training_rows, transform
from .framework import historical_market_features, monthly_membership, sample_manifest
from .macro import LEVELS, align
from .measure import market_membership, measure_record, validity_masks
from .release import assert_sealed_products, code_hash, file_hash
from .report import field_definition
from .tasks import task_matrix


HORIZON = 60
SETS = ('M', 'M+Z')
HISTORY_DESIGN = 'rebuilt-60td-inputs-v1'
MARKET_WINDOWS = (15, 60, 180)
STATE_LAGS = (3, 6, 12)
MACRO_WINDOWS = (15, 60)
BASE_PRODUCTS = ('calendar.parquet', 'missing_policy.json', 'macro/specifications.json')
VIEW_PRODUCTS = tuple(
    f'macro/{view}/{name}.parquet'
    for view in LEVELS
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


def _outcomes(parent, stock_cache, *, past_windows):
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
    replay, derived, historical = [], [], []
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
            for window in past_windows:
                historical.append(measure_record(dates, price, daily, returns, membership,
                    dict(key, horizon=HORIZON), anchor - window, anchor, 'past'))
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
    past = pd.DataFrame(historical)
    if len(past):
        position = dates.get_indexer(past.asof_date)
        expected = position - past.window_length.to_numpy() + 1
        expected = np.where(position >= past.window_length.to_numpy(), expected, -1)
        if (past.duplicated(KEY + ['window_length']).any() or len(past) != len(outcomes) * len(past_windows)
                or not past.window_end.eq(past.asof_date).all()
                or not np.array_equal(dates.get_indexer(past.window_start), expected)):
            raise ValueError('Past window is not aligned on the as-of trading date')
    return outcomes, past, dict(rows=len(replay), numerical_fields=numerical, rtol=1e-12, atol=1e-24,
        stock_partition_sha256=stock_hashes)


def _fit_dictionary(outcomes, parent, *, rebuild_inputs):
    training = training_rows(outcomes)
    if training.empty:
        raise ValueError('No eligible initial 60d labels')
    parameters = fit_transform(training)
    matrix = transform(training, parameters)
    candidates = None
    if rebuild_inputs:
        config = dict(CONFIG, k=[3], block_weeks=16)
        candidates, selected, gmm = dictionary_candidates(training, parameters, config=config, require_each_market=True)
        selection = selected.to_dict() | {'rule': config['selection'], 'training_block_weeks': config['block_weeks']}
    else:
        selected = json.loads((parent.root / 'state_dictionary/dictionary.json').read_text(encoding='utf8'))['selected']
        k, covariance = int(selected['k']), selected['covariance']
        with threadpool_limits(limits=1):
            gmm = model(k, covariance).fit(matrix)
        selection = dict(k=k, covariance=covariance, rule='architecture fixed from the sealed 20d dictionary')
    raw = training.assign(component=gmm.predict(matrix)).groupby('component')[CORE].mean()
    order = raw.sort_values(['return', 'volatility']).index.tolist()
    if not gmm.converged_ or len(order) != gmm.n_components:
        raise RuntimeError('60d state dictionary did not converge to all registered classes')
    fingerprint = digest(training[KEY + CORE].to_dict('records'))
    version = digest(dict(horizon=HORIZON, training=fingerprint, parameters=parameters,
        means=gmm.means_.tolist(), covariances=gmm.covariances_.tolist(), order=order))[:20]
    artifact = dict(gmm=gmm, transform=parameters, order=order, label_version=version, protocol=VERSION,
        selection=selection, horizon=HORIZON)
    metadata = dict(horizon=HORIZON, label_version=version, protocol=VERSION, transform=parameters,
        component_order=order, selected=selection, training_rows=len(training),
        market_counts=training.market_id.value_counts().to_dict(),
        max_label_available_at=training.label_available_at.max(), training_fingerprint=fingerprint)
    return artifact, metadata, training[KEY + ['label_available_at']], candidates


def _macro_change(features, lineage, points, references, specifications):
    """Difference of two contemporaneous release states, respecting series scope."""
    values = features.set_index('asof_date')
    current = values.loc[points.asof_date].copy()
    earlier = values.reindex(references).set_axis(current.index)
    fields = {}
    for spec in specifications:
        sid = spec['series_id']
        prefix = 'macro__' + sid + '__'
        source = lineage[lineage.series_id.eq(sid)].set_index('asof_date')
        now, then = source.loc[current.index], source.reindex(references).set_axis(current.index)
        comparable = now.statistical_scope_id.eq(then.statistical_scope_id).fillna(False)
        if spec['measure_type'] == 'ytd_flow':
            comparable &= now.period_end.dt.year.eq(then.period_end.dt.year).fillna(False)
        fields[prefix + 'change_60d'] = (current[prefix + 'latest'] - earlier[prefix + 'latest']).where(comparable)
    return pd.concat([current, pd.DataFrame(fields, index=current.index)], axis=1).reset_index()


def _rebuild_macro(parent, seal, outcomes):
    fact_path = 'data/standardized/macro/v4/macro_facts.parquet'
    repair_path = 'data/market_state/sources/macro_repairs.parquet'
    source_hashes = {fact_path: seal['original_input_hashes'][fact_path], repair_path: seal['admissions'][repair_path]}
    frames = []
    for relative, path in [(fact_path, ROOT / fact_path), (repair_path, parent.root / 'sources/macro_repairs.parquet')]:
        if file_hash(path) != source_hashes[relative]:
            raise ValueError('Macro source differs from the pinned snapshot: ' + relative)
        frames.append(pd.read_parquet(path))
        if file_hash(path) != source_hashes[relative]:
            raise ValueError('Macro source changed while rebuilding: ' + relative)
    facts = pd.concat(frames, ignore_index=True)
    if not facts.source_record_id.is_unique:
        raise ValueError('Duplicate macro source record IDs')
    audit = parent.root / 'release/macro_period_audit.parquet'
    audit_hash = file_hash(audit)
    specifications = json.loads((parent.root / 'macro/specifications.json').read_text(encoding='utf8'))
    dates = pd.DatetimeIndex(parent.get('calendar').date)
    points = outcomes[['asof_date', 'asof_time']].drop_duplicates().sort_values('asof_date').reset_index(drop=True)
    positions = dates.get_indexer(points.asof_date) - HORIZON
    if (positions < 0).any():
        raise ValueError('60d macro anchors are outside the sealed historical calendar')
    references = dates[positions]
    expanded = pd.DataFrame({'asof_date': pd.DatetimeIndex(points.asof_date).union(references)})
    expanded['asof_time'] = expanded.asof_date.map(clock)
    products = {'macro/history_reference_calendar': points[['asof_date']].assign(reference_date=references)}
    for view in LEVELS:
        values, lineage, _ = align(facts, expanded, view, daily_windows=MACRO_WINDOWS,
            specifications=specifications, audit_path=audit)
        features = _macro_change(values, lineage, points, references, specifications)
        now = lineage[lineage.asof_date.isin(points.asof_date)].reset_index(drop=True)
        if lineage.available_at.gt(lineage.asof_time).any():
            raise ValueError('Macro source arrived after its feature anchor')
        # Identical release snapshots and flags on the parent anchors confirm
        # that the new window statistics did not change the availability policy.
        prefix = 'macro/' + view
        previous = parent.get(prefix + '/features')
        common = [c for c in previous if c in features]
        pd.testing.assert_frame_equal(previous[common], features[common], check_dtype=False)
        previous_lineage = parent.get(prefix + '/lineage').drop(columns='daily_history_parent_ids')
        pd.testing.assert_frame_equal(previous_lineage, now[previous_lineage.columns], check_dtype=False)
        products[prefix + '/features'], products[prefix + '/lineage'] = features, now
        products[prefix + '/history_reference_lineage'] = lineage[lineage.asof_date.isin(references)].reset_index(drop=True)
        print('Rebuilt 60d macro', view, len(features), flush=True)
    if file_hash(audit) != audit_hash:
        raise RuntimeError('Macro period audit changed during the horizon build')
    return products, dict(source_sha256=source_hashes, parent_period_audit_sha256=audit_hash,
        daily_observation_windows=list(MACRO_WINDOWS), released_value_change_trading_days=HORIZON,
        latest_release_and_scope_replayed=True, availability_checked_at_both_anchors=True)


def _rebuilt_spec(parent, market, macro, dictionary, target_version):
    spec = deepcopy(parent.spec)
    mcols = [c for c in market if c not in KEY + ['asof_time', 'feature_version', 'label_version']]
    candidate_z = [c for c in macro if c != 'asof_date']
    series = lambda column: column.removeprefix('macro__').rsplit('__', 1)[0]
    group_for = {series(c): name for name, columns in spec['groups'].items() for c in columns}
    groups = {name: [c for c in candidate_z if group_for.get(series(c)) == name] for name in spec['groups']}
    zcols = [c for c in candidate_z if series(c) in group_for]
    sets = {'M': mcols, 'M+Z': mcols + zcols}
    by_market = {m: {name: [c for c in cols if not c.startswith('cross__' + m.replace('.', '_') + '__')]
        for name, cols in sets.items()} for m in MARKETS}
    version = digest(dict(design=HISTORY_DESIGN, market=MARKET_WINDOWS, state_lags=STATE_LAGS, macro=MACRO_WINDOWS,
        sets=sets, quality=spec['missing_policy_version'], dictionary=dictionary['label_version']))[:20]
    spec.update(sets=sets, by_market=by_market, groups=groups, candidate_macro_columns=candidate_z,
        categorical_columns=[c for c in mcols if c == 'current_state_id' or c.startswith('current_state_id_lag')],
        feature_version=version, target_version=target_version, label_version=dictionary['label_version'],
        horizon=HORIZON, historical_feature_dictionary_version=dictionary['label_version'], historical_input_design=HISTORY_DESIGN)
    return spec


def _rebuilt_fields(fields, products, spec, parent):
    specifications = {s['series_id']: s for s in json.loads((parent.root / 'macro/specifications.json').read_text(encoding='utf8'))}
    rebuild = ['market_features', 'past_window_outcomes', 'current_states'] + [f'macro/{view}/features' for view in LEVELS]
    rows = []
    for table in rebuild:
        for col, dtype in products[table].dtypes.items():
            unit, definition = field_definition(col, specifications)
            if col.startswith(('market__', 'cross__')) and 'H=20' in definition:
                definition = definition.replace('H=20', 'H=' + col.rsplit('_', 1)[-1].removesuffix('d'))
            if col.endswith('__change_60d') and col.startswith('macro__'):
                definition = 'Difference of as-of published values at t and t-60 trading days within one comparable scope'
            if col == 'return':
                definition = 'Past-window endpoint price divided by anchor price minus one, with window_length trading days'
            formal = col in spec['sets']['M+Z']
            rows.append(dict(dataset_id=table, field=col, dtype=str(dtype), unit=unit, definition=definition,
                role='input' if formal else 'source_or_metadata', formal_input=formal,
                nominal_category=col in spec['categorical_columns'], version=VERSION))
    return pd.concat([fields[~fields.dataset_id.isin(rebuild)], pd.DataFrame(rows)], ignore_index=True)


def build_60d(parent, stock_cache, output, *, rebuild_inputs=False):
    """Reaccept a derived target horizon without changing formal snapshot products."""
    output, stock_cache = Path(output).resolve(), Path(stock_cache).resolve()
    if any(output.is_relative_to(p) for p in (OUT, parent.root, stock_cache)):
        raise ValueError('The 60d release needs a separate destination')
    if output.exists():
        raise FileExistsError(output)
    parent_seal_path = parent.root / 'release/seal.json'
    parent_sha256 = file_hash(parent_seal_path)
    parent_seal = json.loads(parent_seal_path.read_text(encoding='utf8'))
    outcomes, past, replay = _outcomes(parent, stock_cache, past_windows=MARKET_WINDOWS if rebuild_inputs else ())
    dictionary, dictionary_meta, training_keys, candidates = _fit_dictionary(outcomes, parent, rebuild_inputs=rebuild_inputs)
    targets = apply_dictionary(outcomes, dictionary, 'future')
    target_version = digest(dict(dictionary=dictionary['label_version'],
        outcomes=outcomes.sort_values(KEY).to_dict('records'), horizon=HORIZON))[:20]
    targets['target_version'] = target_version
    parent_manifest = parent.get('sample_manifest').set_index(KEY[:2])
    source_index = pd.MultiIndex.from_frame(targets[KEY[:2]])
    if len(source_index) != len(parent_manifest) or not source_index.isin(parent_manifest.index).all():
        raise ValueError('Horizon sensitivity needs identical as-of keys')
    extra_products, history = {}, None
    if rebuild_inputs:
        features, current = historical_market_features(outcomes, past, dictionary,
            windows=MARKET_WINDOWS, state_window=HORIZON, lags=STATE_LAGS)
        history_valid = current.set_index(KEY[:2]).measurement_valid.reindex(source_index)
        extra_products, macro_evidence = _rebuild_macro(parent, parent_seal, outcomes)
        extra_products.update(past_window_outcomes=past, current_states=current)
        extra_products['state_dictionary/candidates'] = candidates
        spec = _rebuilt_spec(parent, features, extra_products['macro/historical_reconstructed/features'], dictionary, target_version)
        history = dict(design=HISTORY_DESIGN, market_windows=list(MARKET_WINDOWS), current_state_window=HORIZON,
            cross_market_window=HORIZON, state_lag_weeks=list(STATE_LAGS), macro=macro_evidence,
            all_market_windows_end_at_asof=True, raw_snapshot_reused=True)
    else:
        history_valid = parent_manifest.history_valid.reindex(source_index)
        features = parent.get('market_features').assign(horizon=HORIZON)
        spec = deepcopy(parent.spec)
        spec['sets'] = {name: spec['sets'][name] for name in SETS}
        spec['by_market'] = {market: {name: sets[name] for name in SETS} for market, sets in spec['by_market'].items()}
        feature_version = digest(dict(parent=spec['feature_version'], horizon=HORIZON, information_sets=spec['sets']))[:20]
        spec.update(feature_version=feature_version, target_version=target_version, label_version=dictionary['label_version'],
            horizon=HORIZON, historical_feature_dictionary_version=parent.spec['label_version'])
    if history_valid.isna().any() or len(features) != len(outcomes):
        raise ValueError('Missing historical feature or validity key')
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
    features['feature_version'] = spec['feature_version']
    fields = parent.get('field_dictionary').copy()
    target_fields = fields.dataset_id.isin(['future_window_outcomes', 'supervised_targets'])
    fields.loc[target_fields, 'definition'] = fields.loc[target_fields, 'definition'].str.replace(
        r'\bH\s*=\s*20\b', f'H={HORIZON}', regex=True)
    if rebuild_inputs:
        fields = _rebuilt_fields(fields, dict(extra_products, market_features=features), spec, parent)
    data_tasks = task_matrix(SETS, plans)
    profiles = state_profiles(outcomes, dictionary)

    output.mkdir(parents=True, exist_ok=False)
    for relative in BASE_PRODUCTS + (() if rebuild_inputs else VIEW_PRODUCTS):
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        copyfile(parent.root / relative, path)
        if file_hash(path) != parent_seal['products']['data/market_state/' + relative]:
            raise RuntimeError(f'Sealed input changed during copy: {relative}')
    products = dict(market_features=features, future_window_outcomes=outcomes, supervised_targets=targets,
        sample_manifest=manifest, fold_membership=membership, time_splits=parent.get('time_splits'),
        data_tasks=data_tasks, field_dictionary=fields)
    products.update({'state_dictionary/profiles': profiles, 'state_dictionary/training_keys': training_keys})
    products.update(extra_products)
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
        exact_trading_calendar_offsets=True, same_historical_feature_values=not rebuild_inputs, unchanged_asof_keys_and_months=True,
        mature_train_rows_only=True, development_labels_end_before_test=True,
        evaluation=scored.groupby(['market_id', 'role']).agg(n=('asof_date', 'size'),
            latest_asof=('asof_date', 'max'), latest_label_end=('label_end', 'max')).reset_index().to_dict('records'))
    if rebuild_inputs:
        evidence.update(scope='registered full 60d input, label and state dictionary rebuild', historical_inputs=history)
    write(output / 'release/horizon_acceptance.json', evidence)
    hashes = {'data/market_state/' + p.relative_to(output).as_posix(): file_hash(p)
        for p in sorted(output.rglob('*')) if p.is_file()}
    suffix = '-rebuilt-60td' if rebuild_inputs else '-sensitivity-60td'
    seal = dict(snapshot_id=parent_seal['snapshot_id'] + suffix, cutoff=parent_seal['cutoff'],
        products=hashes, code_hash=code_hash(), target_version=target_version, feature_version=spec['feature_version'],
        dictionary_version=dictionary['label_version'], missing_policy_version=spec['missing_policy_version'],
        horizon=HORIZON, parent_data_version=parent.data_version, parent_seal_sha256=parent_sha256)
    if rebuild_inputs:
        seal['historical_input_design'] = HISTORY_DESIGN
    seal.update(data_version=digest(seal)[:24], status='SEALED_READY_FOR_MODEL_SELECTION', supervised_models_run=0,
        acceptance='release/horizon_acceptance.json')
    write(output / 'release/seal.json', seal)
    assert_sealed_products(data_root=output)
    return seal['data_version']
