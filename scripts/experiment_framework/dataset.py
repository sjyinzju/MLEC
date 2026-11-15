"""Thin development-fold adapter to the single v5 research data authority."""
from dataclasses import dataclass
import json
import pandas as pd
from .common import ROOT, digest, identity, read_json, write_json
from scripts.final_data_foundation import research_inputs as authority
from scripts.final_data_foundation.macro_contract import specifications

VERSION = 'practical-research-data-v5'
DEFAULT_QUALITY = 'historical_reconstructed'
CORE = ['cpi_yoy', 'ppi_yoy', 'pmi_mfg', 'pmi_new_orders', 'm2_yoy', 'shibor_1w', 'shibor_3m']
SUFFIXES = ['latest', 'previous', 'change', 'days_since_release']


def feature_registry(quality=DEFAULT_QUALITY):
    if quality not in authority.LEVELS:
        raise ValueError('Unknown v5 quality: '+quality)
    specs = specifications()
    groups = sorted({s['series_group'] for s in specs})
    by_group = {g: sorted(s['series_id'] for s in specs if s['series_group'] == g and s.get('required', True)) for g in groups}
    selectors = {'M': [], 'core': CORE, **by_group,
                 'all_candidates': sorted({s for ids in by_group.values() for s in ids})}
    selectors['rates_fx'] = sorted(set(by_group['rates']) | {'usdcny_fixing'})
    selectors['full_eligible'] = selectors['all_candidates']
    for group in ['prices', 'growth', 'credit', 'rates_fx']:
        selectors['core_without_'+group] = [s for s in CORE if s not in selectors[group]]
    market = read_json(ROOT/'config/research_v2/feature_whitelist.json')['default_primary_features']
    result = {}
    for group, series in selectors.items():
        name = 'M' if group == 'M' else 'M_plus_Z' if group == 'all_candidates' else 'M_plus_Z_'+group
        cohort = 'core' if group.startswith('core_without_') else 'all_candidates' if group == 'full_eligible' else group
        result[name] = dict(columns=market+[f'macro__{sid}__{suffix}' for sid in series for suffix in SUFFIXES],
            series=series, cohort_series=selectors[cohort], status='eligible',
            sample_version=f'v5:{quality}:{cohort}', quality_version=quality, data_version=VERSION,
            authority='scripts.final_data_foundation.research_inputs.load_dataset',
            missing_policy='Authoritative latest-value eligibility; inactive scopes and missing transforms remain NULL. No imputation in loader.',
            joint_strict_pit_certified=False)
    return result


def build_dataset(quality=DEFAULT_QUALITY):
    """Register bindings only; never overwrite global registries or frozen data."""
    registry = read_json(ROOT/'data/metadata/dataset_registry.json')
    if registry['version'] != VERSION:
        raise ValueError('Unexpected data authority version')
    sets = feature_registry(quality)
    write_json(ROOT/'config/experiments/feature_sets.json', sets)
    write_json(ROOT/'data/metadata/experiment_framework_binding.json', {
        'version': VERSION, 'authority': 'scripts.final_data_foundation.research_inputs.load_dataset',
        'adapter': 'scripts.experiment_framework.dataset.load_dataset',
        'default_quality': quality, 'feature_registry': 'config/experiments/feature_sets.json',
        'sample_count': 599, 'heldout_lock': 'Only dev-* train/validation, before 2023',
        'cohort_rule': 'M and each M+Z comparison must pass the same sample_version',
        'data_status': read_json(ROOT/'data/metadata/remaining_gaps.json')['status'],
        'legacy_results': 'Formal result files remain frozen; they are not v5 results.'})
    return sets


@dataclass
class Dataset:
    X: pd.DataFrame
    y: pd.Series
    metadata: pd.DataFrame
    feature_names: list
    feature_availability: pd.DataFrame
    fold_metadata: dict
    hashes: dict


def authority_hashes(quality=DEFAULT_QUALITY):
    if quality not in authority.LEVELS:
        raise ValueError('Unknown v5 quality: '+quality)
    paths = ['data/metadata/dataset_registry.json', 'data/research_v2/market_features_weekly.parquet',
        'data/research_v2/prediction_targets_weekly.parquet', 'data/research_v2/fold_membership.parquet',
        'data/metadata/market/fold_manifest.parquet',
        str((authority.FEATURES/quality/'macro_weekly.parquet').relative_to(ROOT)),
        str((authority.FEATURES/quality/'macro_lineage.parquet').relative_to(ROOT))]
    return {p:digest(ROOT/p) for p in paths}


def load_dataset(sample_version, feature_set, horizon, fold_id, role, *, label='combined',
                 require_complete_transforms=False):
    if not fold_id.startswith('dev-'):
        raise ValueError('Final evaluation locked')
    if role not in ['train', 'validation']:
        raise ValueError('Invalid role')
    parts = sample_version.split(':')
    if len(parts) != 3 or parts[0] != 'v5':
        raise ValueError('Legacy sample version retired; use v5:<quality>:<cohort>')
    _, quality, cohort = parts
    sets = feature_registry(quality)
    if feature_set not in sets:
        raise ValueError('Unknown feature set: '+feature_set)
    spec = sets[feature_set]
    matching = [s for s in sets.values() if s['sample_version'] == sample_version]
    if not matching or (feature_set != 'M' and spec['sample_version'] != sample_version):
        raise ValueError('Wrong common sample version')
    result = authority.load_dataset(series=matching[0]['cohort_series'], quality=quality, horizon=horizon,
        label=label, require_complete_transforms=require_complete_transforms)
    membership = result['folds']
    selected = membership[membership.fold_id.eq(fold_id) & membership.role.eq(role)]
    plans = pd.read_parquet(ROOT/'data/metadata/market/fold_manifest.parquet').set_index('fold_id')
    if fold_id not in plans.index:
        raise ValueError('Unknown frozen fold')
    mask = result['eligibility']
    meta = result['targets'].merge(mask, on='sample_id', validate='one_to_one', suffixes=('', '_mask'))
    meta = meta[meta.eligible].merge(selected[['sample_id', 'fit_cutoff', 'role']], on='sample_id', validate='one_to_one')
    meta = meta.sort_values('asof_time').reset_index(drop=True)
    if role == 'train' and not meta.label_available_at.le(meta.fit_cutoff).all():
        raise ValueError('Immature training label')
    if not meta.feature_available_at.le(meta.asof_time).all() or not meta.asof_time.dt.year.lt(2023).all():
        raise ValueError('Frozen clock/heldout boundary violation')
    X = meta[['sample_id']].merge(result['features'][['sample_id']+spec['columns']], on='sample_id', validate='one_to_one')[spec['columns']]
    target = f'y_new_{"" if label == "combined" else label+"_"}episode_next{horizon}'
    y = meta[target].astype(int).rename(target)
    meta = meta.drop(columns=[c for c in meta if c.startswith('y_')])
    avail = meta[['sample_id', 'feature_available_at']].copy()
    avail['series_id'] = 'market'
    lin = result['feature_lineage']
    lin = lin[lin.sample_id.isin(meta.sample_id) & lin.series_id.isin(spec['series']) & lin.value.notna()].copy()
    if len(lin):
        lin['feature_available_at'] = lin.available_ats.map(lambda s: max(pd.Timestamp(t) for t in json.loads(s)))
        if not lin.feature_available_at.le(lin.asof_time).all():
            raise ValueError('Macro feature uses future source')
        avail = pd.concat([avail, lin], ignore_index=True)
    plan = plans.loc[fold_id].to_dict()
    plan['fold_id'] = fold_id
    hashes = {'dataset': identity(authority_hashes(quality)), 'feature': identity(spec),
        'protocol': read_json(ROOT/'config/research_v2/protocol_hash.json')['sha256'],
        'selection': identity(dict(sample_version=sample_version, horizon=horizon, label=label,
            require_complete_transforms=require_complete_transforms))}
    return Dataset(X, y, meta, list(X.columns), avail, plan, hashes)
