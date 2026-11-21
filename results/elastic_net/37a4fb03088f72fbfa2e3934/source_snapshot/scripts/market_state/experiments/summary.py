"""Explicit-run cross-family aggregation with synchronized inference and Holm gates."""
from pathlib import Path
import pandas as pd
import numpy as np
from ..common import digest
from .artifacts import read_json, atomic_json, atomic_parquet
from .reports import write_table
from .scoring import synchronized_bootstrap, holm


def summarize_runs(run_directories, destination):
    roots = [Path(p).resolve() for p in run_directories]
    if len(set(roots)) != len(roots) or not roots:
        raise ValueError('Unique explicit run directories required')
    manifests = [read_json(p / 'manifest.json') for p in roots]
    if any(m['purpose'] != 'RESEARCH' or not m['test_complete'] for m in manifests):
        raise ValueError('Cross-model summary accepts completed RESEARCH test runs only')
    if len({m['model'] for m in manifests}) != len(manifests):
        raise ValueError('One explicit run per family required')
    configs = [read_json(p / 'config.resolved.yaml') for p in roots]
    config = configs[0]
    for m, c in zip(manifests, configs):
        for key in ['data_version', 'feature_version', 'target_version', 'dictionary_version', 'contract_version', 'protocol_hash']:
            if m['versions'][key] != manifests[0]['versions'][key]:
                raise RuntimeError('Incompatible common research identity: ' + key)
        if c['statistics'] != config['statistics'] or c['warning'] != config['warning'] or m['suite'] != manifests[0]['suite']:
            raise RuntimeError('Incompatible preregistered inference/warning/suite rules')
    pairs = []
    for root, m in zip(roots, manifests):
        # Validate raw selected artifacts again, not just a potentially stale summary CSV.
        from .reports import analysis_frames, paired_differences
        scores, _, _, _ = analysis_frames(root, 'test')
        assignments = read_json(root / 'test/selection/assignments.json')
        schema = read_json(root / assignments[0]['artifact'] / 'context.json')['schema']
        frame = paired_differences(scores, schema, 'test')
        frame['run_id'] = m['run_id']
        pairs.append(frame)
    pairs = pd.concat(pairs, ignore_index=True)
    metadata = pairs[['comparison_id', 'family', 'market_id', 'task', 'mode', 'kind', 'metric', 'left', 'right', 'run_id']].drop_duplicates()
    averaged = pairs.groupby(['comparison_id', 'asof_date'], as_index=False).loss_difference.mean()
    tables = []
    stats = config['statistics']
    periods = [('all', averaged)] + [(str(int(y)), f) for y, f in averaged.groupby(averaged.asof_date.dt.year)]
    for year, frame in periods:
        for width in stats['block_weeks']:
            result = synchronized_bootstrap(frame, block_weeks=width, repetitions=stats['repetitions'],
                seed=stats['seed'], confidence=stats['confidence']).merge(metadata, on='comparison_id', validate='one_to_one')
            result['year'], result['p_holm'] = year, np.nan
            result['holm_status'] = 'OUTSIDE_PREREGISTERED_PRIMARY_SET'
            primary = (result.market_id.eq(stats['primary_market']) & result.task.eq(stats['primary_task']) &
                result.metric.eq(stats['primary_metric']) & result['mode'].eq('retuned_core') & result.kind.eq('core'))
            family_set = set(stats['holm_families'])
            selected = primary & result.family.isin(family_set)
            if year == 'all' and width == stats['block_weeks'][0]:
                if set(result.loc[selected, 'family']) == family_set:
                    result.loc[selected, 'p_holm'] = holm(result.loc[selected, 'p_one_sided'])
                    result.loc[selected, 'holm_status'] = 'COMPLETE_PREREGISTERED_NONLINEAR_FAMILY_SET'
                else:
                    result.loc[primary, 'holm_status'] = 'PENDING_PREREGISTERED_NONLINEAR_FAMILIES'
            tables.append(result)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    write_table(destination, 'cross_model_increment', pd.concat(tables, ignore_index=True))
    for name in ['core_classification', 'core_regression', 'macro_groups', 'warning_value', 'runtime_quality', 'coverage_status']:
        frames = [pd.read_csv(root / 'tables' / (name + '.csv')).assign(run_id=m['run_id']) for root, m in zip(roots, manifests)]
        write_table(destination, name, pd.concat(frames, ignore_index=True), markdown=name not in ['runtime_quality', 'coverage_status'])
    atomic_parquet(destination / 'paired_differences.parquet', pairs)
    missing = sorted({'elastic_net', 'rbf_svm', 'random_forest', 'catboost'} - {m['model'] for m in manifests})
    atomic_json(destination / 'manifest.json', dict(run_ids={m['model']: m['run_id'] for m in manifests},
        sources=[str(p) for p in roots], missing_families=missing, statistics=stats))
    (destination / 'report.md').write_text('# Explicit-run model summary\n\nCompleted families: ' + ', '.join(m['model'] for m in manifests) +
        '.\n\nMissing families: ' + (', '.join(missing) or 'none') + '. No missing family is imputed.\n', encoding='utf8')
    return destination
