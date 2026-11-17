"""Shared original-unit scores; predictions are checked before truth is attached."""
from dataclasses import replace
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score
from ..common import CORE, KEY
from ..evaluation import multiclass_losses, continuous_losses
from ..model_contract import (DIMENSIONS, EvaluationContext, prepare_evaluation, validate_output,
    validate_probabilities)

LOG_EPS = 1e-15


def score_predictions(output, prediction_context, truth, *, task, fixed_scale=None):
    """Explicitly restrict to existing mature score members, preserving their order."""
    validate_output(output, prediction_context, task=task, schema=truth.target_schema)
    aligned = truth.keys.merge(output, on=KEY, how='left', validate='one_to_one', indicator=True)
    if not aligned._merge.eq('both').all():
        raise ValueError('Missing predictions for mature scoring keys')
    aligned = aligned.drop(columns='_merge')[output.columns].reset_index(drop=True)
    context = replace(prediction_context, keys=truth.keys.copy())
    scores = prepare_evaluation(aligned, truth, EvaluationContext(context, task, fixed_scale))
    if not len(scores):
        return add_losses(scores, task, truth.target_schema, fixed_scale)
    return add_losses(scores, task, truth.target_schema, fixed_scale)


def add_losses(scores, task, schema, fixed_scale=None):
    result = scores.copy()
    if task == 'classification':
        ids = schema['class_ids']
        p = result[['predicted_state_prob_' + str(c) for c in ids]].to_numpy(float)
        validate_probabilities(p, ids)
        y = result.future_state_id.to_numpy()
        losses = multiclass_losses(y, p, ids)
        for name in losses:
            result[name] = losses[name].to_numpy()
        ix = np.array([ids.index(v) for v in y], dtype=int)
        result['log_floor_hit'] = p[np.arange(len(p)), ix] <= LOG_EPS
        result['correct'] = result.predicted_state_id.eq(result.future_state_id)
        result['loss'] = result.log_loss
    else:
        if fixed_scale is None or fixed_scale['columns'] != CORE:
            raise ValueError('Fixed seven-target evaluation scale required')
        actual = result[CORE].to_numpy(float)
        predicted = result[['predicted_' + c for c in CORE]].to_numpy(float)
        if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
            raise ValueError('Non-finite original-unit scoring values')
        losses = continuous_losses(actual, predicted)
        scale = np.asarray(fixed_scale['scale'])
        if not np.isfinite(scale).all() or (scale <= 0).any():
            raise ValueError('Invalid fixed evaluation scale')
        for j, c in enumerate(CORE):
            result['absolute_error_' + c] = losses['absolute_error'][:, j]
            result['squared_error_' + c] = losses['squared_error'][:, j]
        for dim, columns in DIMENSIONS.items():
            ix = [CORE.index(c) for c in columns]
            result['squared_' + dim] = (losses['squared_error'][:, ix] / scale[ix] ** 2).mean(axis=1)
            result['absolute_' + dim] = (losses['absolute_error'][:, ix] / scale[ix]).mean(axis=1)
        result['loss'] = result[['squared_' + d for d in DIMENSIONS]].mean(axis=1)
        result['absolute_five_dimension'] = result[['absolute_' + d for d in DIMENSIONS]].mean(axis=1)
    if len(result) and not np.isfinite(result.loss.to_numpy(float)).all():
        raise ValueError('Non-finite sample losses')
    return result


def classification_metrics(scores, schema):
    ids = schema['class_ids']
    n = len(scores)
    if not n:
        return dict(n=0, reason='NO_MATURE_SCORE_ROWS'), [], [], []
    y, pred = scores.future_state_id.to_numpy(), scores.predicted_state_id.to_numpy()
    p = scores[['predicted_state_prob_' + str(c) for c in ids]].to_numpy(float)
    validate_probabilities(p, ids)
    matrix = np.array([[(y == a).__and__(pred == b).sum() for b in ids] for a in ids])
    per_class, f1s, recalls = [], [], []
    reliability = []
    for j, c in enumerate(ids):
        tp, support, count = matrix[j, j], matrix[j].sum(), matrix[:, j].sum()
        precision = float(tp / count) if count else None
        recall = float(tp / support) if support else None
        f1 = float(2 * tp / (support + count)) if support + count else None
        per_class.append(dict(class_id=c, support=int(support), predicted=int(count),
            precision=precision, recall=recall, f1=f1,
            reason='NO_TRUE_CLASS' if not support else 'NO_PREDICTED_CLASS' if not count else 'DEFINED'))
        if f1 is not None:
            f1s.append(f1)
        if recall is not None:
            recalls.append(recall)
        bins = np.minimum((p[:, j] * 10).astype(int), 9)
        for b in range(10):
            take = bins == b
            reliability.append(dict(class_id=c, bin=b, n=int(take.sum()),
                mean_probability=float(p[take, j].mean()) if take.any() else None,
                observed_fraction=float((y[take] == c).mean()) if take.any() else None))
    auc = None
    reason = 'MISSING_CLASS_SUPPORT'
    if len(ids) > 2 and all((y == c).any() and (y != c).any() for c in ids):
        auc = float(roc_auc_score(y, p, labels=ids, multi_class='ovr'))
        reason = 'DEFINED'
    result = dict(n=n, log_loss=float(scores.log_loss.mean()), brier=float(scores.brier.mean()),
        accuracy=float((y == pred).mean()), macro_f1=float(np.mean(f1s)),
        balanced_accuracy=float(np.mean(recalls)), log_floor_hits=int(scores.log_floor_hit.sum()),
        roc_auc_ovr=auc, auc_reason=reason, macro_f1_defined_classes=len(f1s), recall_defined_classes=len(recalls))
    confusion = [dict(actual=a, predicted=b, count=int(matrix[i, j]))
        for i, a in enumerate(ids) for j, b in enumerate(ids)]
    return result, per_class, confusion, reliability


def regression_metrics(scores):
    if not len(scores):
        return dict(n=0, reason='NO_MATURE_SCORE_ROWS')
    result = dict(n=len(scores), five_dimension_squared=float(scores.loss.mean()),
        five_dimension_absolute=float(scores.absolute_five_dimension.mean()),
        economic_boundary_rows=int(scores.economic_bound_violations.ne('[]').sum()))
    for c in CORE:
        result['mae_' + c] = float(scores['absolute_error_' + c].mean())
        result['rmse_' + c] = float(np.sqrt(scores['squared_error_' + c].mean()))
    for dim in DIMENSIONS:
        result['squared_' + dim] = float(scores['squared_' + dim].mean())
        result['absolute_' + dim] = float(scores['absolute_' + dim].mean())
    return result


def synchronized_bootstrap(differences, *, block_weeks, repetitions, seed, confidence=.95):
    """One calendar draw for every comparison; seed repeats must be collapsed first.

    Input schema: comparison_id, asof_date, loss_difference. A comparison includes
    its market; seeds are averaged on the same dated sample, never stacked.
    """
    required = ['comparison_id', 'asof_date', 'loss_difference']
    if not set(required) <= set(differences) or not len(differences):
        raise ValueError('Nonempty dated differences required')
    if differences.duplicated(['comparison_id', 'asof_date']).any():
        raise ValueError('Duplicate independent units; average paired seeds first')
    if not np.isfinite(differences.loss_difference.to_numpy(float)).all():
        raise ValueError('Non-finite paired differences')
    d = differences.copy()
    d['week'] = pd.DatetimeIndex(d.asof_date).to_period('W').start_time
    calendar = pd.date_range(d.week.min(), d.week.max(), freq='7D')
    ids = sorted(d.comparison_id.unique())
    sums = d.pivot_table(index='week', columns='comparison_id', values='loss_difference', aggfunc='sum').reindex(index=calendar, columns=ids).fillna(0).to_numpy()
    counts = d.pivot_table(index='week', columns='comparison_id', values='loss_difference', aggfunc='count').reindex(index=calendar, columns=ids).fillna(0).to_numpy()
    means = sums.sum(axis=0) / counts.sum(axis=0)
    n = len(calendar)
    width = min(block_weeks, n)
    rng = np.random.default_rng(seed)
    draws = np.full((repetitions, len(ids)), np.nan)
    for b in range(repetitions):
        starts = rng.integers(0, n - width + 1, size=int(np.ceil(n / width)))
        indices = (starts[:, None] + np.arange(width)).ravel()[:n]
        numerator, denominator = sums[indices].sum(axis=0), counts[indices].sum(axis=0)
        np.divide(numerator, denominator, out=draws[b], where=denominator > 0)
    alpha = (1 - confidence) / 2
    result = []
    for j, name in enumerate(ids):
        values = draws[:, j]
        values = values[np.isfinite(values)]
        result.append(dict(comparison_id=name, mean=float(means[j]),
            lower=float(np.quantile(values, alpha)), upper=float(np.quantile(values, 1 - alpha)),
            p_one_sided=float((1 + (values - means[j] >= means[j]).sum()) / (len(values) + 1)),
            block_weeks=block_weeks, repetitions=repetitions, valid_repetitions=len(values),
            calendar_weeks=n, empty_calendar_weeks=int((counts[:, j] == 0).sum()),
            n=int(counts[:, j].sum()), method='synchronized_moving_calendar_week_blocks_centered_null'))
    return pd.DataFrame(result)


def holm(pvalues):
    values = np.asarray(pvalues, float)
    if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
        raise ValueError('All preregistered tests must have finite p values')
    order = np.argsort(values, kind='stable')
    adjusted = np.minimum(1., np.maximum.accumulate(values[order] * (len(values) - np.arange(len(values)))))
    output = np.empty_like(adjusted)
    output[order] = adjusted
    return output
