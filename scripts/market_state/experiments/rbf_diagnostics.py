"""Development-only macro vintage, perturbation and conditional-increment checks."""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from ..common import CORE, KEY, digest
from ..evaluation import multiclass_losses
from ..framework import load_dataset
from ..model_contract import IDENTITY, fit_inputs, training_partition, transform_inputs
from ..models.rbf_geometry import BlockGeometry
from .artifacts import atomic_json, atomic_parquet, file_manifest, read_json
from .scoring import add_losses, regression_metrics, synchronized_bootstrap


def permute_validation(X, keys, lineage, *, weeks, seed):
    dates = keys.asof_date
    bins = dates.dt.to_period('W-FRI').astype('int64')
    if len(bins) < 2 * weeks or not bins.diff().iloc[1:].eq(1).all():
        return None
    n = len(bins) // weeks
    order = np.random.default_rng(int(digest([seed, str(dates.iloc[0])])[:8], 16)).permutation(n)
    if np.array_equal(order, np.arange(n)):
        order = np.roll(order, 1)
    indices = np.r_[np.concatenate([np.arange(b * weeks, (b + 1) * weeks) for b in order]),
        np.arange(n * weeks, len(bins))]
    columns = [c for c in X if c.removeprefix('missing__') in lineage]
    shifted = X.copy()
    shifted[columns] = X[columns].iloc[indices].to_numpy()
    return shifted, keys.assign(source_asof_date=dates.iloc[indices].to_numpy())


def vintage_audit(store, quality):
    spec = read_json(store.root / 'macro/specifications.json')
    frequency = {r['series_id']: r['frequency'] for r in spec}
    data = store.get('macro/' + quality + '/lineage')
    data = data[data.series_id.isin(store.spec['formal_macro_series']) & data.asof_date.lt('2023-01-01')]
    rows = []
    for series, part in data.sort_values('asof_date').groupby('series_id', sort=True):
        used = part[part.source_record_id.notna()]
        late = used.actual_vintage_available_at.gt(used.asof_time)
        rows.append(dict(series_id=series, group=part.series_group.iloc[0], frequency=frequency[series],
            weeks=len(part), value_weeks=len(used), source_records=used.source_record_id.nunique(),
            economic_periods=used.period_end.nunique(),
            new_source_record_weeks=int(used.source_record_id.ne(used.source_record_id.shift()).sum()),
            effective_release_after_asof=int(used.available_at.gt(used.asof_time).sum()),
            actual_vintage_after_asof=int(late.sum()), actual_vintage_unrecorded=int(used.actual_vintage_available_at.isna().sum()),
            vintage_grades={str(k): int(n) for k, n in used.quality.value_counts().items()},
            statuses={str(k): int(n) for k, n in part.status.value_counts().items()}))
    return rows


def _conditional_group(pipeline, evidence):
    config, store = pipeline.config, pipeline.store
    market, task = evidence['market_id'], evidence['task']
    rules = config['rbf_design']['conditional']
    profile = rules[task]
    anchor = next(row for row in evidence['full_review'] if row['parameters']['gamma_factor'] == rules['market_gamma']
        and all(row['parameters'][k] == v for k, v in profile.items()))
    if not anchor['valid']:
        return [], dict(market_id=market, task=task, status='ANCHOR_FAILED')
    frames = [pipeline.checked_scores(pipeline.journal.records[t]) for t in anchor['tasks']]
    all_scores = pd.concat(frames, ignore_index=True)
    schema = store.target_schema()
    ids = schema['class_ids']
    pred_columns = ['predicted_state_prob_' + str(c) for c in ids] if task == 'classification' else ['predicted_' + c for c in CORE]
    lineage = {c: g for g, columns in store.spec['groups'].items() for c in columns}
    result = []
    for fold, current in zip(pipeline.development, frames):
        args = dict(market_id=market, task=task, information_set='M+Z', fold_id=fold, quality=config['quality'], store=store)
        train = load_dataset(**args, role='train')
        matched = train.keys.merge(all_scores[KEY + pred_columns], on=KEY, validate='one_to_one')
        if len(matched) < rules['min_mature_rows']:
            continue
        # Intersect accepted OOF prediction keys with THIS month's mature training membership.
        cutoff = train.metadata.fit_cutoff.iloc[0]
        prior = training_partition(train, matched[KEY], role='train', fit_cutoff=cutoff)
        pd.testing.assert_frame_equal(prior.keys, matched[KEY])
        pre = fit_inputs(prior)
        X = transform_inputs(pre, prior)
        projection = BlockGeometry.fit(X, lineage, 'compact', .5)
        _, z = projection.coordinates(X)
        if not z.shape[1]:
            continue
        target = prior.y.future_state_id.to_numpy()[:, None] == np.asarray(ids) if task == 'classification' else prior.y[CORE].to_numpy()
        scale = np.ones(len(ids)) if task == 'classification' else np.asarray(
            read_json(pipeline.root / pipeline.journal.records[anchor['tasks'][0]]['artifact'] / 'context.json')['fixed_scale']['scale'])
        residual = (target - matched[pred_columns].to_numpy()) / scale
        beta = np.linalg.solve(z.T @ z + rules['ridge'] * np.eye(z.shape[1]), z.T @ residual)
        prediction = load_dataset(**args, role='prediction')
        _, future_z = projection.coordinates(transform_inputs(pre, prediction))
        correction = prediction.keys.copy()
        correction[pred_columns] = (future_z @ beta) * scale
        prediction = current[KEY].merge(correction, on=KEY, validate='one_to_one')
        corrected = current.copy()
        corrected[pred_columns] = current[pred_columns] + prediction[pred_columns]
        if task == 'classification':
            probabilities = np.clip(corrected[pred_columns].to_numpy(), 1e-15, 1.)
            probabilities /= probabilities.sum(axis=1, keepdims=True)
            corrected[pred_columns] = probabilities
            corrected['predicted_state_id'] = np.asarray(ids)[probabilities.argmax(axis=1)]
        fixed = dict(scale=scale.tolist(), columns=CORE) if task == 'regression' else None
        loss = add_losses(corrected, task, schema, fixed)
        result.append(current[KEY].assign(task=task, fold_id=fold, anchor_candidate_id=anchor['candidate_id'],
            fit_cutoff=str(cutoff), mature_oof_train_rows=len(prior.keys),
            latest_train_label=str(prior.metadata.label_available_at.max()), anchor_loss=current.loss,
            conditional_loss=loss.loss, loss_difference=current.loss - loss.loss))
    return result, dict(market_id=market, task=task, status='EXECUTED' if result else 'INSUFFICIENT_MATURE_OOF_SUPPORT')


def development_diagnostics(pipeline, selection):
    root = pipeline.root / 'development/rbf_diagnostics'
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / 'vintages.json', vintage_audit(pipeline.store, pipeline.config['quality']))
    assignments = read_json(pipeline.root / 'development/selection/assignments.json')
    perturbed, conditional, conditions = [], [], []
    for assignment in assignments:
        i = assignment['identity']
        if i['mode'] == 'fixed_full_params' and i['information_set'] == 'M+Z':
            path = pipeline.root / assignment['artifact'] / 'perturbed_losses.parquet'
            if path.exists():
                frame = pd.read_parquet(path)
                perturbed.append(frame.assign(task=i['task'], fold_id=i['fold_id'],
                    loss_difference=frame.loss_perturbed - frame.loss_real))
    for evidence in selection.values():
        if evidence['information_set'] != 'M':
            continue
        key = '|'.join([evidence['market_id'], evidence['task'], 'M+Z'])
        if selection[key]['winner']['score'] < evidence['winner']['score']:
            conditions.append(dict(market_id=evidence['market_id'], task=evidence['task'], status='NOT_TRIGGERED_B_LOSS_IMPROVED'))
            continue
        frames, summary = _conditional_group(pipeline, evidence)
        conditional.extend(frames)
        conditions.append(summary)
    summaries = {}
    for name, frames in [('perturbed', perturbed), ('conditional', conditional)]:
        if not frames:
            continue
        weekly = pd.concat(frames, ignore_index=True)
        weekly['comparison_id'] = weekly.market_id + '|' + weekly.task
        atomic_parquet(root / (name + '_weekly.parquet'), weekly)
        rules = pipeline.config['statistics']
        table = synchronized_bootstrap(weekly, block_weeks=rules['block_weeks'][0],
            repetitions=rules['repetitions'], seed=rules['seed'], confidence=rules['confidence'])
        summaries[name] = table.to_dict('records')
    files = {name: sha for name, sha in file_manifest(root).items() if name != 'manifest.json'}
    atomic_json(root / 'manifest.json', dict(conditions=conditions, summaries=summaries, files=files))


def _baseline_intervals(scores, config):
    result, labels = [], []
    for (market, task), part in scores.groupby(['market_id', 'task']):
        truth = ['future_state_id'] if task == 'classification' else CORE
        columns = KEY + ['fold_id', 'fit_cutoff', 'quality'] + IDENTITY + truth
        comparisons = part[part['mode'].eq('retuned_core')]
        baseline = part[part['mode'].eq('baseline')]
        for family, left in baseline.groupby('family'):
            for info, right in comparisons.groupby('information_set'):
                a = left.sort_values(KEY).reset_index(drop=True)
                b = right.sort_values(KEY).reset_index(drop=True)
                pd.testing.assert_frame_equal(a[columns], b[columns], check_exact=True)
                key = '|'.join([market, task, family, info])
                result.append(a[['asof_date', 'loss']].assign(comparison_id=key, loss_difference=a.loss - b.loss))
                labels.append(dict(comparison_id=key, market_id=market, task=task, baseline=family, information_set=info,
                    baseline_mean=float(a.loss.mean()), model_mean=float(b.loss.mean())))
    frames = pd.concat(result, ignore_index=True)
    rules = config['statistics']
    return pd.concat([synchronized_bootstrap(frames, block_weeks=width, repetitions=rules['repetitions'],
        seed=rules['seed'], confidence=rules['confidence']).merge(pd.DataFrame(labels), on='comparison_id', validate='one_to_one')
        for width in rules['block_weeks']], ignore_index=True)


def _probability_summary(frames, schema):
    rows = []
    ids = schema['class_ids']
    for (market, info), part in frames.groupby(['market_id', 'information_set']):
        observed = part[part.observed_state_id.notna()]
        labels = observed.observed_state_id.to_numpy(dtype=int)
        for kind in ['score_softmax', 'calibrated']:
            p = observed[[kind + '_' + str(c) for c in ids]].to_numpy()
            losses = multiclass_losses(labels, p, ids)
            for j, c in enumerate(ids):
                event = labels == c
                support = int(event.sum())
                raw = observed['decision_' + str(c)]
                metrics = {}
                if 0 < support < len(labels):
                    metrics.update(raw_score_auc=float(roc_auc_score(event, raw)), probability_auc=float(roc_auc_score(event, p[:, j])),
                        average_precision=float(average_precision_score(event, p[:, j])))
                rows.append(dict(market_id=market, information_set=info, probability=kind, class_id=c, n=len(labels),
                    support=support, raw_score_mean=float(raw.mean()), raw_score_std=float(raw.std(ddof=0)),
                    observed_frequency=float(event.mean()), predicted_frequency=float(p[:, j].mean()),
                    probability_bias=float(p[:, j].mean() - event.mean()),
                    log_loss=float(losses.log_loss.mean()), brier=float(losses.brier.mean()), **metrics))
    return pd.DataFrame(rows)


def study_tables(root, stage, assignments, scores, schema, config):
    """Collect selected diagnostics without fitting or reopening model selection."""
    probabilities, kernel_rows, train_rows = [], [], []
    for assignment in assignments:
        i = assignment['identity']
        if i['mode'] != 'retuned_core':
            continue
        path = root / assignment['artifact']
        details = read_json(path / 'kernel_diagnostics.json')
        g = details['matched_kernel']
        meta = dict(market_id=i['market_id'], task=i['task'], fold_id=i['fold_id'], information_set=i['information_set'],
            fit_id=assignment['fit_id'], representation=i['parameters']['representation'], macro_weight=i['parameters']['macro_weight'])
        for kind in ['train_train', 'prediction_train']:
            stats = g[kind]
            kernel_rows.append(dict(meta, pairing=kind, train_rows=len(g['train_positions']), pairs=stats['pairs'],
                gamma_base=g['gamma_base'], gamma_factor=g['gamma_factor'], legacy_gamma=g['legacy_gamma'],
                **{field: stats.get(field) for field in ['macro_mean_share', 'legacy_kernel_rms_change', 'zero_weight_kernel_rms_change']},
                exponent_median=stats.get('exponent', [None] * 7)[3], kernel_median=stats.get('kernel', [None] * 7)[3]))
        if i['task'] == 'classification':
            frame = pd.read_parquet(path / 'probability_evidence.parquet')
            for name, value in meta.items():
                frame[name] = value
            probabilities.append(frame)
        else:
            for target, metrics in details['training_metrics'].items():
                p = i['parameters'].get('target_parameters', {}).get(target, i['parameters'])
                train_rows.append(dict(meta, target=target, C=p['C'], epsilon=p['epsilon'], **metrics))
    prob = pd.concat(probabilities, ignore_index=True)
    atomic_parquet(root / stage / 'metrics/rbf_probability_evidence.parquet', prob)
    products = dict(rbf_kernel_geometry=pd.DataFrame(kernel_rows), rbf_regression_train=pd.DataFrame(train_rows),
        rbf_probability_diagnostics=_probability_summary(prob[prob.score_role.eq('OUTER_PREDICTION')], schema),
        rbf_paired_baselines=_baseline_intervals(scores, config))
    if stage == 'development':
        selections = read_json(root / 'development/selection/search.json')
        rows, turnover = [], []
        for key, evidence in selections.items():
            meta = {k: evidence[k] for k in ['market_id', 'task', 'information_set']}
            for entry in evidence['full_review']:
                rows.append(dict(meta, candidate_id=entry['candidate_id'], valid=entry['valid'], development_loss=entry['score'],
                    scored_weeks=entry.get('n'), **entry['parameters'],
                    **{c + '_fixed_scale_mse': loss for c, loss in entry.get('target_scores', {}).items()}))
                if meta['market_id'] == '000905.SH' and meta['task'] == 'regression' and meta['information_set'] in ['M', 'M+Z'] and entry['valid']:
                    monthly = [pd.read_parquet(root / 'development/fits' / fit_id / 'losses.parquet')
                        for fit_id in entry['fit_ids']]
                    reg = regression_metrics(pd.concat(monthly))
                    turnover.append(dict(meta, candidate_id=entry['candidate_id'], **entry['parameters'],
                        **{k: v for k, v in reg.items() if k.endswith('_turnover')}))
        products.update(rbf_development_candidate_losses=pd.DataFrame(rows), rbf_turnover_matched=pd.DataFrame(turnover))
    return products
