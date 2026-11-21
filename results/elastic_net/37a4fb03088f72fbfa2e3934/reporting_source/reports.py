"""Rebuildable research delivery from explicit selected task assignments; never fits."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from ..common import CORE, KEY, digest
from ..framework import paired_losses
from ..models import REGISTRY
from ..model_contract import (PredictionContext, validate_output, key_hash, truth_hash,
    IDENTITY, OUTPUT_CONTEXT_FIELDS)
from .artifacts import read_json, atomic_json, atomic_parquet, check_files
from .scoring import (add_losses, classification_metrics, regression_metrics, synchronized_bootstrap, holm)
from .warnings import evaluate_workpoint, warning_curve, window_clusters

GROUP = ['family', 'market_id', 'task', 'mode', 'information_set', 'seed']
WARN_GROUP = GROUP + ['signal']


def retry_counts(task):
    """Physical attempts and solver continuations, including reused artifacts."""
    history = task.get('attempt_history', [])
    attempts = max([task.get('attempts', 0), len(history)] + [h.get('attempt', 0) for h in history])
    outer = max(0, attempts - 1)
    solver = sum(d.get('attempt', 1) > 1 for d in task.get('diagnostics', [])
        if d.get('component', 'estimator') != 'calibrator')
    return dict(task_attempts=attempts, task_retries=outer, solver_retries=solver, retries=outer + solver)


def analysis_frames(root, stage, purpose='RESEARCH', *, artificial=False):
    root = Path(root)
    manifest = read_json(root / 'manifest.json')
    if stage not in ['development', 'test']:
        raise ValueError('Unknown report stage')
    if purpose != 'RESEARCH' and not (artificial and purpose == 'ARTIFICIAL_TEST_ONLY'):
        raise ValueError('SMOKE_ONLY/ARTIFICIAL_TEST_ONLY are excluded from research reports')
    if manifest['purpose'] != purpose or not manifest[stage + '_complete']:
        raise RuntimeError('Incomplete or non-research stage')
    assignments = read_json(root / stage / 'selection/assignments.json')
    scores, warnings, quality, coverage = [], [], [], []
    physical = set()
    schema = None
    for assignment in assignments:
        task = read_json(root / stage / 'tasks' / (assignment['task_id'] + '.json'))
        if task['status'] != 'SUCCEEDED' or task['identity'] != assignment['identity'] or task['fit_id'] != assignment['fit_id'] or task['artifact'] != assignment['artifact']:
            raise RuntimeError('Selected task assignment is invalid')
        identity = task['identity']
        if identity['purpose'] != purpose or identity['versions'] != manifest['versions']:
            raise RuntimeError('Unaccepted purpose/version in research results')
        directory = root / task['artifact']
        check_files(directory, task['files'])
        ctx = read_json(directory / 'context.json')
        if ctx['purpose'] != purpose:
            raise RuntimeError('Artificial/smoke artifact in selected analysis')
        output = pd.read_parquet(directory / 'predictions.parquet')
        prediction = PredictionContext(keys=output[KEY], **ctx['prediction'])
        schema = ctx['schema']
        validate_output(output, prediction, task=identity['task'], schema=schema)
        if key_hash(output[KEY]) != ctx['prediction_keys'] or len(output) != ctx['expected_predictions']:
            raise RuntimeError('Prediction coverage mismatch')
        frame = pd.read_parquet(directory / 'losses.parquet')
        targets = schema['columns'][identity['task']]
        if len(frame) != ctx['mature_rows'] or key_hash(frame[KEY]) != ctx['scoring_keys'] or truth_hash(frame[targets]) != ctx['scoring_truth']:
            raise RuntimeError('Saved scoring keys or truth changed')
        subset = frame[KEY].merge(output, on=KEY, how='left', validate='one_to_one')[output.columns]
        pd.testing.assert_frame_equal(frame[output.columns].reset_index(drop=True), subset.reset_index(drop=True))
        recomputed = add_losses(frame, identity['task'], schema, ctx['fixed_scale'])
        for col in recomputed:
            if col not in frame or not recomputed[col].equals(frame[col]):
                raise RuntimeError('Saved sample loss mismatch: ' + col)
        metadata = {k: identity[k] for k in ['family', 'task', 'mode', 'seed']}
        metadata.update(fit_id=assignment['fit_id'], task_id=assignment['task_id'], purpose=purpose)
        frame = frame.assign(**metadata)
        scores.append(frame)
        w = pd.read_parquet(directory / 'warning.parquet')
        w = w.assign(**metadata, information_set=identity['information_set'])
        warnings.append(w)
        coverage.append(dict(stage=stage, **{k: identity[k] for k in ['family', 'market_id', 'task', 'mode', 'information_set', 'seed', 'fold_id']},
            fit_id=assignment['fit_id'], expected=ctx['expected_predictions'], actual=len(output),
            mature=len(frame), unscored=ctx['unscored_rows'], status=ctx['scoring_status'],
            unique_physical_fit=assignment['fit_id'] not in physical))
        if assignment['fit_id'] not in physical:
            quality.append(dict(stage=stage, fit_id=assignment['fit_id'], family=identity['family'],
                market_id=identity['market_id'], task=identity['task'], seed=identity['seed'],
                information_set=identity['information_set'], fold_id=identity['fold_id'], status='SUCCEEDED',
                backend=identity['backend'], elapsed_seconds=task.get('elapsed_seconds', ctx['elapsed_seconds']),
                estimator_fit_calls=task.get('estimator_fit_calls', len(ctx['diagnostics'])),
                certified_zero_slopes=sum(d.get('solver') == 'certified_zero_slopes' for d in task.get('diagnostics', [])),
                peak_rss_bytes=task.get('process_usage', {}).get('peak_rss_bytes'),
                calibration_fit_calls=task.get('calibration_fit_calls', 0),
                internal_svc_fit_calls=sum(d.get('phase') == 'internal' for d in task.get('diagnostics', [])),
                final_svc_fit_calls=sum(d.get('phase') == 'final' and d.get('target') == 'classification' for d in task.get('diagnostics', [])),
                convergence_warnings=sum(any(w['category'] == 'ConvergenceWarning' for w in r['warnings']) for r in task.get('diagnostics', ctx['diagnostics'])),
                numerical_warnings=sum(any(w['category'] == 'RuntimeWarning' for w in r['warnings']) for r in task.get('diagnostics', ctx['diagnostics'])),
                **retry_counts(task),
                interrupted_fit_calls_unknown=task.get('interrupted_fit_calls_unknown', False),
                economic_boundary_rows=int(frame.economic_bound_violations.ne('[]').sum()) if identity['task'] == 'regression' else 0))
        physical.add(assignment['fit_id'])
    # Candidate fits/failures also belong in the runtime quality audit, even if not selected.
    for path in sorted((root / stage / 'tasks').glob('*.json')):
        task = read_json(path)
        if task['fit_id'] in physical:
            continue
        i = task['identity']
        diagnostics = task.get('diagnostics', [])
        quality.append(dict(stage=stage, fit_id=task['fit_id'], family=i['family'], market_id=i['market_id'],
            task=i['task'], seed=i['seed'], information_set=i['information_set'], fold_id=i['fold_id'],
            status=task['status'], backend=i['backend'], elapsed_seconds=task.get('elapsed_seconds'),
            estimator_fit_calls=task.get('estimator_fit_calls', len(diagnostics)),
            certified_zero_slopes=sum(d.get('solver') == 'certified_zero_slopes' for d in diagnostics),
            peak_rss_bytes=task.get('process_usage', {}).get('peak_rss_bytes'),
            calibration_fit_calls=task.get('calibration_fit_calls', 0),
            convergence_warnings=sum(any(w['category'] == 'ConvergenceWarning' for w in d['warnings']) for d in diagnostics),
            numerical_warnings=sum(d.get('numerical_failure', False) for d in diagnostics),
            **retry_counts(task), failure_kind=task.get('failure_kind'),
            error=task.get('error'), selected=False))
        physical.add(task['fit_id'])
    frames = pd.concat(scores, ignore_index=True) if scores else pd.DataFrame()
    if len(frames) and frames.duplicated(GROUP + ['asof_date', 'horizon']).any():
        raise RuntimeError('Selected observations duplicated within an analysis/seed')
    return frames, pd.concat(warnings, ignore_index=True), pd.DataFrame(quality), pd.DataFrame(coverage)


def performance_tables(scores, schema, stage):
    classification, regression, per_class, confusion, reliability = [], [], [], [], []
    for values, frame in scores.groupby(GROUP, sort=True):
        metadata = dict(zip(GROUP, values), stage=stage)
        periods = [('all', frame)] + [(str(int(y)), f) for y, f in frame.groupby(frame.asof_date.dt.year)]
        for year, part in periods:
            meta = dict(metadata, year=year)
            if metadata['task'] == 'classification':
                metric, classes, matrix, bins = classification_metrics(part, schema)
                metric.update(majority_class_share=float(part.future_state_id.value_counts(normalize=True).max()),
                    uniform_probability_log_loss=float(np.log(len(schema['class_ids']))))
                classification.append(dict(meta, **metric))
                per_class.extend(dict(meta, **r) for r in classes)
                confusion.extend(dict(meta, **r) for r in matrix)
                reliability.extend(dict(meta, **r) for r in bins)
            else:
                regression.append(dict(meta, **regression_metrics(part)))
    def seed_summary(rows):
        frame = pd.DataFrame(rows)
        summaries = []
        keys = [k for k in GROUP if k != 'seed'] + ['stage', 'year']
        for values, part in frame.groupby(keys, sort=True):
            if part.n.nunique() != 1:
                raise RuntimeError('Seed scoring cohorts differ')
            row = dict(zip(keys, values), seed='mean', seed_count=len(part), n=int(part.n.iloc[0]))
            if 'auc_reason' in part:
                row['auc_reason'] = ';'.join(sorted(part.auc_reason.dropna().unique()))
            for col in frame.select_dtypes(include='number'):
                if col not in ['seed', 'n']:
                    row[col] = float(part[col].mean()) if part[col].notna().any() else None
                    row[col + '_seed_sd'] = float(part[col].std(ddof=1)) if len(part) > 1 and part[col].notna().all() else None
            summaries.append(row)
        return pd.concat([frame, pd.DataFrame(summaries)], ignore_index=True)
    classification, regression = seed_summary(classification), seed_summary(regression)
    # Same dated cohorts; a seed-average row keeps n unchanged.
    for index, row in regression.iterrows():
        base = regression[regression.family.eq('naive_persistence') & regression.market_id.eq(row.market_id) &
            regression.year.eq(row.year) & regression.seed.eq('mean')]
        if len(base) == 1 and int(base.n.iloc[0]) == int(row.n):
            reference = base.iloc[0]
            for metric in ['five_dimension_squared'] + ['mae_' + c for c in CORE] + ['rmse_' + c for c in CORE]:
                regression.loc[index, 'relative_improvement_vs_persistence_' + metric] = (reference[metric] - row[metric]) / reference[metric] if reference[metric] != 0 else np.nan
    for index, row in classification.iterrows():
        for family, metric in [('naive_history', 'log_loss'), ('naive_current_state', 'accuracy'),
                ('naive_initial_frequency', 'log_loss'), ('naive_intercept', 'log_loss')]:
            base = classification[classification.family.eq(family) & classification.market_id.eq(row.market_id) &
                classification.year.eq(row.year) & classification.seed.eq('mean')]
            if len(base) == 1 and int(base.n.iloc[0]) == int(row.n):
                sign = -1 if metric == 'log_loss' else 1
                classification.loc[index, 'gain_vs_' + family] = sign * (row[metric] - base[metric].iloc[0])
    return classification, regression, pd.DataFrame(per_class), pd.DataFrame(confusion), pd.DataFrame(reliability)


def paired_differences(scores, schema, stage):
    records = []
    grouping = ['family', 'market_id', 'task', 'mode', 'seed']
    for values, frame in scores[~scores.family.str.startswith('naive_')].groupby(grouping, sort=True):
        metadata = dict(zip(grouping, values), stage=stage)
        task, mode = metadata['task'], metadata['mode']
        infos = set(frame.information_set)
        definitions = [('core', 'M', 'M+Z')]
        if mode == 'fixed_full_params':
            for information in sorted(infos - {'M', 'M+Z'}):
                definitions.append(('delete' if information.startswith('M+Z_without_') else 'add',
                    information if information.startswith('M+Z_without_') else 'M',
                    'M+Z' if information.startswith('M+Z_without_') else information))
        metrics = {'log_loss': 'log_loss', 'brier': 'brier', 'error_rate': 'incorrect'} if task == 'classification' else {
            'five_dimension_squared': 'loss', 'five_dimension_absolute': 'absolute_five_dimension',
            **{'squared_' + d: 'squared_' + d for d in schema['dimensions']},
            **{'mae_' + c: 'absolute_error_' + c for c in CORE}}
        for kind, left, right in definitions:
            if left not in infos or right not in infos:
                raise RuntimeError('Missing required paired information reference')
            a, b = frame[frame.information_set.eq(left)].copy(), frame[frame.information_set.eq(right)].copy()
            if task == 'classification':
                a['incorrect'], b['incorrect'] = 1. - a.correct.astype(float), 1. - b.correct.astype(float)
            for metric, col in metrics.items():
                l, r = a.assign(loss=a[col]), b.assign(loss=b[col])
                pair = paired_losses(l, r, task=task, schema=schema)
                meta = dict(metadata, kind=kind, left=left, right=right, metric=metric)
                identity = {k: v for k, v in meta.items() if k != 'seed'}
                pair['comparison_id'] = digest(identity)[:24]
                result = pair[KEY + ['loss_M', 'loss_MZ', 'loss_difference']].copy()
                for field in IDENTITY + ['fold_id', 'fit_cutoff', 'model_id', 'quality', 'target_adapter_version']:
                    result[field] = pair[field + '_M']
                for field in ['model_version', 'preprocessing_version', 'fit_id', 'task_id']:
                    result[field + '_left'], result[field + '_right'] = pair[field + '_M'], pair[field + '_MZ']
                for name, value in meta.items():
                    result[name] = value
                result['comparison_id'] = digest(identity)[:24]
                records.append(result)
    return pd.concat(records, ignore_index=True)


def increment_tables(pairs, config):
    metadata_columns = ['comparison_id', 'family', 'market_id', 'task', 'mode', 'kind', 'left', 'right', 'metric', 'stage']
    meta = pairs[metadata_columns].drop_duplicates()
    if meta.comparison_id.duplicated().any():
        raise RuntimeError('Comparison ID collision')
    expected_seeds = pairs.groupby('comparison_id').seed.nunique()
    counts = pairs.groupby(['comparison_id', 'asof_date', 'horizon']).seed.nunique()
    if any(v != expected_seeds.loc[k[0]] for k, v in counts.items()):
        raise RuntimeError('Missing paired seed/date; cannot use a smaller denominator')
    averaged = pairs.groupby(['comparison_id', 'asof_date'], as_index=False)[['loss_difference', 'loss_M', 'loss_MZ']].mean()
    results = []
    periods = [('all', averaged)] + [(str(int(year)), frame) for year, frame in averaged.groupby(averaged.asof_date.dt.year)]
    stats = config['statistics']
    for year, frame in periods:
        for width in stats['block_weeks']:
            result = synchronized_bootstrap(frame, block_weeks=width, repetitions=stats['repetitions'],
                seed=stats['seed'], confidence=stats['confidence'])
            result = result.merge(meta, on='comparison_id', validate='one_to_one')
            loss = frame.groupby('comparison_id')[['loss_M', 'loss_MZ']].mean()
            baseline = loss.loss_M
            result['mean_loss_left'] = result.comparison_id.map(baseline)
            result['mean_loss_right'] = result.comparison_id.map(loss.loss_MZ)
            result['max_absolute_weekly_difference'] = result.comparison_id.map(
                frame.loss_difference.abs().groupby(frame.comparison_id).max())
            result['relative_improvement'] = [float(row['mean'] / baseline.loc[row['comparison_id']]) if baseline.loc[row['comparison_id']] != 0 else None for row in result.to_dict('records')]
            result['numerical_equivalence_tolerance'] = result.comparison_id.map(
                lambda key: 128. * np.finfo(float).eps * max(1., abs(baseline.loc[key])))
            result['effect_interpretation'] = [
                'NUMERICALLY_EQUIVALENT' if r['max_absolute_weekly_difference'] <= r['numerical_equivalence_tolerance'] else
                'SMALL_RELATIVE_EFFECT_BELOW_0.1_PERCENT' if pd.notna(r['relative_improvement']) and abs(r['relative_improvement']) < .001 else
                'LOWER_LOSS_WITH_MACRO' if r['mean'] > 0 else 'HIGHER_LOSS_WITH_MACRO'
                for r in result.to_dict('records')]
            result['year'] = year
            result['seed_count'] = result.comparison_id.map(expected_seeds)
            result['p_holm'] = np.nan
            result['holm_status'] = 'LINEAR_REFERENCE_NOT_IN_PRIMARY_FAMILY' if config['model'] == 'elastic_net' else 'PENDING_PREREGISTERED_NONLINEAR_FAMILIES'
            results.append(result)
    result = pd.concat(results, ignore_index=True)
    return result[result.kind.eq('core')].reset_index(drop=True), result[~result.kind.eq('core')].reset_index(drop=True), averaged


def loss_diagnostics(averaged, increment, config):
    main = increment[increment.year.eq('all') & increment.block_weeks.eq(8)
        & increment['mode'].eq('retuned_core') & increment.metric.isin(['log_loss', 'five_dimension_squared'])]
    keys = ['comparison_id', 'market_id', 'task', 'metric']
    weekly = averaged.merge(main[keys], on='comparison_id', validate='many_to_one')
    weekly['year'] = weekly.asof_date.dt.year
    weekly['absolute_difference'] = weekly.loss_difference.abs()
    weekly['contribution_rank'] = weekly.groupby('comparison_id').absolute_difference.rank(method='first', ascending=False)
    n = weekly.groupby('comparison_id').asof_date.transform('size')
    weekly['extreme_5pct'] = weekly.contribution_rank.le(np.floor(.05 * n))
    quantiles = weekly.groupby(keys + ['year'])[['loss_M', 'loss_MZ', 'loss_difference']].quantile(
        [0., .05, .25, .5, .75, .95, 1.]).rename_axis(index=keys + ['year', 'quantile']).reset_index()
    sensitivity = synchronized_bootstrap(weekly.loc[~weekly.extreme_5pct],
        block_weeks=8, repetitions=config['statistics']['repetitions'], seed=config['statistics']['seed'],
        confidence=config['statistics']['confidence']).merge(main[keys], on='comparison_id', validate='one_to_one')
    sensitivity['removed_weeks'] = sensitivity.comparison_id.map(weekly.groupby('comparison_id').extreme_5pct.sum())
    sensitivity['analysis'] = 'EXPLORATORY_REMOVE_TOP_5_PERCENT_ABSOLUTE_PAIRED_DIFFERENCES'
    return weekly, quantiles, sensitivity


def warning_tables(warnings, locked, stage):
    points, curves = [], []
    for values, frame in warnings.groupby(WARN_GROUP, sort=True):
        metadata = dict(zip(WARN_GROUP, values), stage=stage)
        key = '|'.join(str(v) for v in values)
        if key not in locked['warning_workpoints']:
            raise RuntimeError('No development-locked warning workpoint for ' + key)
        for point in locked['warning_workpoints'][key]:
            points.append(dict(metadata, **point, **evaluate_workpoint(frame, point['threshold'])))
        curve = warning_curve(frame)
        for name, value in metadata.items():
            curve[name] = value
        curves.append(curve)
    return pd.DataFrame(points), pd.concat(curves, ignore_index=True)


def write_table(directory, name, frame, *, markdown=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + '.csv')
    temp = path.with_name(path.name + '.partial')
    frame.to_csv(temp, index=False)
    temp.replace(path)
    if markdown:
        text = frame.to_markdown(index=False, floatfmt='.6g') if len(frame) else 'No completed observations in this scope.'
        (directory / (name + '.md')).write_text(text + '\n', encoding='utf8')


def figures(directory, classification, regression, increment, groups, confusion, reliability, curves):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Panels use raw seed results or their displayed means, never independent-seed inference.
    main = classification[(classification['seed'].astype(str) == 'mean') & classification.year.eq('all') & classification['mode'].eq('retuned_core')]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for info, f in main.groupby('information_set'):
        ax.plot(f.market_id, f.log_loss, marker='o', label=info)
    ax.set(ylabel='Multiclass log loss', title='Core classification (mean seed losses)')
    ax.legend()
    fig.tight_layout(); fig.savefig(directory / 'core_classification.png', dpi=140); plt.close(fig)
    main = regression[(regression['seed'].astype(str) == 'mean') & regression.year.eq('all') & regression['mode'].eq('retuned_core')]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for info, f in main.groupby('information_set'):
        ax.plot(f.market_id, f.five_dimension_squared, marker='o', label=info)
    ax.set(ylabel='Fixed-scale five-dimension squared loss', title='Core regression')
    ax.legend()
    fig.tight_layout(); fig.savefig(directory / 'core_regression.png', dpi=140); plt.close(fig)
    for target, metric in [('classification', 'log_loss'), ('regression', 'five_dimension_squared')]:
        subset = increment[increment.task.eq(target) & increment.metric.eq(metric) & increment['mode'].eq('retuned_core') & increment.block_weeks.eq(8) & increment.year.ne('all')]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        for market, f in subset.groupby('market_id'):
            f = f.sort_values('year')
            ax.plot(f.year, f['mean'], marker='o', label=market)
        ax.axhline(0, color='black', linewidth=.7)
        ax.set(ylabel='M loss minus M+Z loss', title='Annual macro increment: ' + target)
        ax.legend()
        fig.tight_layout(); fig.savefig(directory / ('annual_increment_' + target + '.png'), dpi=140); plt.close(fig)
    selected = reliability[reliability.year.eq('all') & reliability['mode'].eq('retuned_core')]
    fig, ax = plt.subplots(figsize=(7, 5))
    for (info, cls), f in selected.groupby(['information_set', 'class_id']):
        f = f[f.n.gt(0)].copy()
        f['probability_sum'] = f.mean_probability * f.n
        f['observed_sum'] = f.observed_fraction * f.n
        bins = f.groupby('bin')[['probability_sum', 'observed_sum', 'n']].sum()
        ax.plot(bins.probability_sum / bins.n, bins.observed_sum / bins.n, marker='.', label=f'{info}: class {cls}')
    ax.plot([0, 1], [0, 1], color='black', linewidth=.7)
    ax.set(xlabel='Predicted probability', ylabel='Observed fraction', title='Reliability (pooled seed probability bins)')
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(directory / 'reliability.png', dpi=140); plt.close(fig)
    selected = confusion[confusion.year.eq('all') & confusion['mode'].eq('retuned_core')]
    markets = sorted(selected.market_id.unique())
    fig, axes = plt.subplots(1, len(markets), figsize=(4 * len(markets), 4), squeeze=False)
    for market, ax in zip(markets, axes[0]):
        f = selected[selected.market_id.eq(market) & selected.information_set.eq('M+Z')]
        matrix = f.groupby(['actual', 'predicted'])['count'].mean().unstack(fill_value=0)
        ax.imshow(matrix.to_numpy(), cmap='Blues')
        ax.set(title=market, xlabel='Predicted', ylabel='Actual', xticks=range(len(matrix)), yticks=range(len(matrix)))
    fig.tight_layout(); fig.savefig(directory / 'confusion.png', dpi=140); plt.close(fig)
    if len(groups):
        f = groups[groups.year.eq('all') & groups.block_weeks.eq(8) & groups.metric.isin(['log_loss', 'five_dimension_squared'])]
        fig, ax = plt.subplots(figsize=(12, 5))
        f = f.groupby(['task', 'kind', 'left', 'right'])['mean'].mean()
        ax.bar(range(len(f)), f.to_numpy())
        ax.set(xticks=range(len(f)), xticklabels=[' / '.join(x) for x in f.index], ylabel='Paired loss gain (market mean)', title='Fixed-parameter macro groups')
        ax.tick_params(axis='x', labelrotation=90, labelsize=7)
        ax.axhline(0, color='black', linewidth=.7)
        fig.tight_layout(); fig.savefig(directory / 'macro_groups.png', dpi=140); plt.close(fig)
    for signal in ['risk_downside', 'predicted_drawdown']:
        f = curves[curves.signal.eq(signal) & curves['mode'].eq('retuned_core')]
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        for (market, info, seed), part in f.groupby(['market_id', 'information_set', 'seed']):
            label = f'{market} {info} s{seed}'
            axes[0].plot(part.false_positive_rate, part.recall, alpha=.5, label=label)
            axes[1].plot(part.recall, part.precision, alpha=.5)
            axes[2].plot(part.burden, part.loss_coverage, alpha=.5)
        for ax, x, y in zip(axes, ['False positive rate', 'Recall', 'Alarm burden'], ['Recall', 'Precision', 'Drawdown coverage']):
            ax.set(xlabel=x, ylabel=y)
        axes[0].legend(fontsize=6)
        fig.suptitle(signal + ' (window-level; segments reported separately)')
        fig.tight_layout(); fig.savefig(directory / ('warning_' + signal + '.png'), dpi=140); plt.close(fig)



def state_support_windows(reference, warnings):
    windows = warnings.loc[warnings.signal.eq('state_0_probability'),
        KEY + ['label_start', 'label_end']].drop_duplicates()
    # Empty unscored tail artifacts can promote the concatenated date column
    # to object. Restore date typing before verifying all mature-score keys.
    windows['asof_date'] = pd.to_datetime(windows.asof_date)
    result = reference[KEY + ['future_state_id']].merge(
        windows, on=KEY, how='left', validate='one_to_one')
    if result[['label_start', 'label_end']].isna().any().any():
        raise RuntimeError('Missing state support window for a mature scoring key')
    return result


def elastic_report(root, manifest, stage, locked, products, coverage, quality):
    risk = locked['risk_definition']
    lines = ['# Elastic Net 市场状态预测复算', '',
        f'运行 `{manifest["run_id"]}` · 阶段 `{stage}` · 套件 `{manifest["suite"]}`',
        '', '## 运行和数值验收', '',
        '零系数候选仅在训练频率截距、完整 KKT 和原惩罚目标同时成立时采用解析解。',
        '旧求解器在全部斜率为零时可能首轮退出，随机更新后的截距仍有一阶残差。',
        '七项回归沿用增广 Lasso/LARS 和独立对偶间隙。纯 L1 路径出现已复现的内部形状错误时，记录原异常并调用现有对偶 QP。收紧停止条件的续解告警仍保存。',
        '',
        f'选定逻辑月任务 {len(coverage):,}。阶段物理任务 {len(quality):,}，其中通过 {int(quality.status.eq("SUCCEEDED").sum()):,}，失败 {int(quality.status.eq("FAILED").sum()):,}。',
        f'记录到的估计器拟合调用 {int(quality.estimator_fit_calls.sum()):,}，零迭代解析解 {int(quality.certified_zero_slopes.sum()):,}。',
        f'最大片内进程峰值内存 {quality.peak_rss_bytes.max() / 1024**3:.2f} GiB。各进程峰值可能出现于不同时刻。',
        '', '## 主比较', '',
        '正值表示 M＋Z 降低损失。区间使用 8 周同步日历区块和 2,000 次重采样。'
        '4 周、12 周及逐年结果见明细。单侧 p 值检验正向增益，负向改善区间按其本身方向解读。'
        '非线性模型主检验尚未齐备，Holm 校正值留空。', '']
    increment = products['macro_increment']
    primary = increment[increment.year.eq('all') & increment.block_weeks.eq(8)
        & increment['mode'].eq('retuned_core') & increment.metric.isin(['log_loss', 'five_dimension_squared'])]
    for row in primary.to_dict('records'):
        lines.append(f'- {row["market_id"]} {row["task"]}，M {row["mean_loss_left"]:.5g}，'
            f'M＋Z {row["mean_loss_right"]:.5g}，增益 {row["mean"]:.5g}，'
            f'95% 区间 [{row["lower"]:.5g}, {row["upper"]:.5g}]，{row["n"]} 周。')
    classification = products['core_classification']
    regression = products['core_regression']
    lines += ['', '### 金融特征与朴素基准', '']
    for market in sorted(primary.market_id.unique()):
        cm = classification[(classification.market_id == market) & (classification.year == 'all')
            & (classification.seed == 'mean') & (classification.information_set == 'M') & (classification['mode'] == 'retuned_core')].iloc[0]
        rm = regression[(regression.market_id == market) & (regression.year == 'all')
            & (regression.seed == 'mean') & (regression.information_set == 'M') & (regression['mode'] == 'retuned_core')].iloc[0]
        lines.append(f'- {market}，M 相对平滑训练频率基准的 Log Loss 降幅 {cm.gain_vs_naive_history:.5g}，'
            f'相对历史 20 日持续基准的五维平方误差降幅 {rm.relative_improvement_vs_persistence_five_dimension_squared:.2%}。')
    lines += ['', '## 预警和解释', '',
        f'字典风险映射为 `{json.dumps(risk["risks"], ensure_ascii=False)}`。'
        '同一状态映射产生相同的类别概率信号。低换手仅描述交易活跃度，流动性判断同时参考 Amihud 价格冲击。',
        '连续风险辅助结果对七项原指标分别使用初始训练期不利方向的 90% 分位。'
        '报警阈值仅在开发期按固定负担选取。重叠窗口簇只表示窗口合并后的事件段，统计推断使用区块 Bootstrap。',
        '状态 0 的平均精确率、ROC-AUC、校准、逐类召回、无支持提示和各负担检出率见下列明细。', '',
        '- [分类和朴素基准](tables/core_classification.csv) · [分类支持与排序](tables/class_precision_recall.csv) · [校准](tables/reliability.csv)',
        '- [七目标和五维回归](tables/core_regression.csv) · [预警](tables/warning_value.csv) · [类别支持](tables/class_support.csv)',
        '- [逐周损失和贡献](tables/weekly_loss_diagnostics.csv) · [年度分位数](tables/weekly_loss_quantiles.csv) · [删极端周敏感性](tables/extreme_week_sensitivity.csv)',
        '- [固定参数比较](tables/fixed_parameter_sensitivity.csv) · [宏观分组](tables/macro_groups.csv) · [宏观发布时间审计](tables/macro_lineage_audit.csv)',
        '- [运行质量](tables/runtime_quality.csv) · [覆盖](tables/coverage_status.csv) · [候选有效率](tables/candidate_status.csv)',
        '', '## 研究范围', '',
        ('本阶段包含全部 96 个原定固定 M＋Z 参数配置。' if manifest['suite'] == 'full'
         else '本阶段包含核心 M/M＋Z 和两种共同参数比较。'),
        '同参比较使用 M 和 M＋Z 各自的开发获胜参数进行交叉对照。分组、同参和极端周分析为辅助探索。',
        '宏观特征按可得日、口径和来源类型审计。历史重建视图包含代理可得时间，无法证明当年的真实实时数据版本。',
        '信息年龄、发布时钟和金融模块的独立特征投影仍需单独的数据视图。',
        '2023 年之后的测试时代此前已被查看，本运行属于实现修复后的复算。',
        '', '## 来源身份', '']
    lines.extend(f'- {key} `{value}`' for key, value in manifest['versions'].items())
    return '\n'.join(lines) + '\n'


def summarize(root, *, stage='test', artificial=False):
    root = Path(root).resolve()
    manifest = read_json(root / 'manifest.json')
    config = read_json(root / 'config.resolved.yaml')
    locked = read_json(root / 'selection.lock.json')
    from ..release import file_hash
    if manifest['lock_hash'] != file_hash(root / 'selection.lock.json') or digest({k: v for k, v in locked.items() if k != 'content_hash'}) != locked['content_hash']:
        raise RuntimeError('Summarize requires the unmodified registered lock')
    if locked['versions'] != manifest['versions'] or locked['run_id'] != manifest['run_id']:
        raise RuntimeError('Report lock identity mismatch')
    scores, warnings, quality, coverage = analysis_frames(root, stage, manifest['purpose'], artificial=artificial)
    assignments = read_json(root / stage / 'selection/assignments.json')
    schema = read_json(root / assignments[0]['artifact'] / 'context.json')['schema']
    classification, regression, classes, confusion, reliability = performance_tables(scores, schema, stage)
    pairs = paired_differences(scores, schema, stage)
    increment, groups, averaged = increment_tables(pairs, config)
    mean_classification = classification[classification.seed.eq('mean')]
    gain_index = mean_classification.set_index(['family', 'market_id', 'mode', 'information_set', 'year'])
    for table in [increment, groups]:
        for index, row in table[table.task.eq('classification')].iterrows():
            a = gain_index.loc[(row.family, row.market_id, row['mode'], row.left, row.year)]
            b = gain_index.loc[(row.family, row.market_id, row['mode'], row.right, row.year)]
            for metric in ['accuracy', 'macro_f1', 'balanced_accuracy']:
                table.loc[index, metric + '_gain_right_minus_left'] = b[metric] - a[metric]
    warning, curves = warning_tables(warnings, locked, stage)
    tables = root / 'tables' if stage == 'test' else root / 'development/tables'
    plots = root / 'figures' if stage == 'test' else root / 'development/figures'
    products = {'core_classification': classification, 'core_regression': regression,
        'macro_increment': increment, 'macro_groups': groups, 'warning_value': warning,
        'runtime_quality': quality, 'coverage_status': coverage,
        'class_precision_recall': classes, 'confusion_matrix': confusion,
        'reliability': reliability, 'warning_curves': curves}
    if manifest['model'] == 'elastic_net':
        weekly, quantiles, sensitivity = loss_diagnostics(averaged, increment, config)
        preflight = read_json(root / 'preflight.json')
        support = [dict(period='initial_train', **r) for r in locked['risk_definition'].get('initial_class_support', [])]
        reference = scores[scores.family.eq('elastic_net') & scores.task.eq('classification')
            & scores['mode'].eq('retuned_core') & scores.information_set.eq('M') & scores.seed.eq(locked['seeds']['classification'][0])]
        reference = state_support_windows(reference, warnings)
        for market, frame in reference.groupby('market_id'):
            for label in schema['class_ids']:
                affected = frame[frame.future_state_id.eq(label)]
                support.append(dict(period=stage, market_id=market, class_id=label, n=len(frame),
                    support=len(affected), overlapping_window_clusters=window_clusters(affected)))
        candidates_summary = []
        for evidence in read_json(root / 'development/selection/search.json').values():
            for phase in ('coarse', 'full_review'):
                for c in evidence[phase]:
                    candidates_summary.append(dict(market_id=evidence['market_id'], task=evidence['task'],
                        information_set=evidence['information_set'], phase=phase, **{k: c[k] for k in ('candidate_id','valid','score')},
                        selected=c['candidate_id'] == evidence['winner']['candidate_id'], **c['parameters']))
        products.update(fixed_parameter_sensitivity=increment[increment['mode'].ne('retuned_core')],
            weekly_loss_diagnostics=weekly, weekly_loss_quantiles=quantiles, extreme_week_sensitivity=sensitivity,
            class_support=pd.DataFrame(support), monthly_training_support=pd.DataFrame(preflight.get('train_class_support', [])),
            macro_lineage_audit=pd.DataFrame(preflight.get('macro_lineage_audit', [])),
            candidate_status=pd.DataFrame(candidates_summary))
    for name, table in products.items():
        write_table(tables, name, table, markdown=name in ['core_classification', 'core_regression', 'macro_increment', 'macro_groups', 'warning_value'])
    atomic_parquet(root / stage / 'losses/paired_differences.parquet', pairs)
    atomic_parquet(root / stage / 'losses/seed_averaged_differences.parquet', averaged)
    atomic_parquet(root / stage / 'metrics/selected_scores.parquet', scores)
    figures(plots, classification, regression, increment, groups, confusion, reliability, curves)
    primary = increment[increment.year.eq('all') & increment.block_weeks.eq(8) & increment['mode'].eq('retuned_core') & increment.metric.isin(['log_loss', 'five_dimension_squared'])]
    lines = [f'# {manifest["model"]}: {stage}', '',
        f'run_id: `{manifest["run_id"]}`; purpose: `{manifest["purpose"]}`; suite: `{manifest["suite"]}`.', '',
        'Development results were used for selection and warning workpoints; test results are time-forward evaluations of the locked plan.', '',
        '## Prediction performance', '',
        'See [classification](tables/core_classification.md) and [seven-target regression](tables/core_regression.md). The `mean` seed rows average losses/metrics, not probabilities. `n` counts dated windows once.', '',
        'Naive historical frequency, current memberships/state persistence and past-20-day continuous persistence are included. Core models retain all seven targets and report original-unit errors.', '',
        '## Macro increment', '']
    for row in primary.to_dict('records'):
        direction = row['effect_interpretation']
        lines.append(f'- {row["market_id"]} {row["task"]}: {row["mean"]:.6g}, 95% interval [{row["lower"]:.6g}, {row["upper"]:.6g}]; {direction}.')
    lines += ['', 'Intervals use synchronous calendar blocks, including empty weeks; centered-null one-sided p values use finite-repetition correction. Annual results and 4/12-week sensitivities accompany the 8-week primary block. Accuracy/F1 gains are right-minus-left aggregate metrics; intervals in each row refer only to the named sample loss.', '',
        'Elastic Net is the linear reference. Cross-model Holm correction is pending the complete preregistered nonlinear family set; no adjusted value is fabricated.', '',
        '## Warning value', '',
        'See [warning workpoints](tables/warning_value.md). Burden targets 5/10/20/30% were specified before execution; thresholds come only from development. Detection–false alarm, precision–recall and drawdown coverage–burden curves are saved. Alarm segments and repeat windows are separate from window metrics. Undefined event contrasts are reported explicitly; no unique economic optimum or crisis lead time is claimed.', '',
        '## Coverage and limits', '',
        f'Selected logical monthly tasks: {len(coverage)}; unique physical fits: {int(coverage.unique_physical_fit.sum())}. Unscored prediction rows across analysis references: {int(coverage.unscored.sum())}; these are immature windows, not normal-state labels or failed predictions.', '',
        'Runtime quality includes failed candidates, actual estimator/calibrator calls, convergence retries and economic boundary violations. ' + ('RBF-SVM records kernel scale, support counts, solver status and training-only time calibration; kernels have no linear coefficient interpretation.' if manifest['model'] == 'rbf_svm' else 'Penalized coefficients describe prediction associations, not causal effects.'), '',
        ('Completed full suite: twelve formal information sets in fixed_full_params.' if manifest['suite'] == 'full' else 'Completed core suite only: M/M+Z; all 96 fixed_full_params configurations were NOT EXECUTED.') +
        ' Information-clock, publication-lag, market-module, data-view and alternative-dictionary extensions are unimplemented and were not executed. Registered unimplemented model families: ' + ', '.join(k for k, v in REGISTRY.items() if not v['implemented']) + '. This report contains only the explicitly selected family/run.', '',
        'The test era was viewed in the first Elastic Net run. This implementation correction is a recomputation after known defects, not a first unseen independent test. Numerical equivalence uses 128 machine eps times max(1, baseline loss); effects below 0.1% relative loss are labeled small, not erased. These descriptive labels do not change scores, candidate ranking or bootstrap calculations. Accuracy/argmax changes alone do not establish warning value; inspect probability losses, balanced accuracy, macro-F1, per-class recall and confusion together.', '',
        f'Data version: `{manifest["versions"]["data_version"]}`. Interface: `{manifest["versions"]["interface_code_hash"]}`. Experiment code: `{manifest["versions"]["experiment_code_hash"]}`.', '']
    if artificial:
        lines.insert(2, '**ARTIFICIAL_TEST_ONLY — orchestration verification, not research evidence.**')
    report_path = root / 'report.md' if stage == 'test' else root / 'development/report.md'
    body = (elastic_report(root, manifest, stage, locked, products, coverage, quality)
        if manifest['model'] == 'elastic_net' and not artificial else '\n'.join(lines))
    report_path.write_text(body, encoding='utf8')
    atomic_json(root / stage / 'report_manifest.json', dict(stage=stage, run_id=manifest['run_id'], purpose=manifest['purpose'],
        tables={name: len(frame) for name, frame in products.items()}, lock_hash=manifest['lock_hash']))
    return products
