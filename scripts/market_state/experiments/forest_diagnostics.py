"""Retrospective forest sensitivity of native out-of-sample predictions."""
from dataclasses import replace

import numpy as np
import pandas as pd

from ..common import CORE, KEY
from ..framework import load_dataset
from ..model_contract import DIMENSIONS, transform_inputs
from .scoring import score_predictions


def earlier_macro_rows(prediction, store, task):
    """Match intact earlier weekly macro vectors at a fixed thirteen-week lag."""
    weeks = prediction.keys.asof_date.dt.to_period('W-FRI') - 13
    months = set(weeks.dt.start_time.dt.strftime('%Y-%m')) | set(weeks.dt.end_time.dt.strftime('%Y-%m'))
    available = set(store.get('time_splits').fold_id)
    frames = []
    for fold in sorted(months & available):
        donor = load_dataset(market_id=prediction.context['market_id'], task=task,
            information_set=prediction.context['information_set'], quality=prediction.context['quality'],
            fold_id=fold, role='prediction', store=store)
        frames.append(donor.X_macro.assign(source_asof_date=donor.keys.asof_date))
    if not frames:
        return None
    donors = pd.concat(frames, ignore_index=True)
    donors.index = donors.source_asof_date.dt.to_period('W-FRI')
    matched = weeks.isin(donors.index)
    shifted = donors.loc[weeks[matched]].set_axis(prediction.keys.index[matched])
    if not shifted.source_asof_date.lt(prediction.keys.loc[matched, 'asof_date']).all():
        raise ValueError('Macro perturbation donor must precede recipient')
    return shifted


def forest_perturbation_losses(model, prediction, context, truth, scores, *, fixed_scale, interactions, prior=None):
    """Compare calendar-month rotation and a past quarter's weekly macro vector."""
    if not len(prediction.X_macro.columns):
        return None
    variants = []
    if len(prediction.keys) >= 2:
        donors = np.roll(np.arange(len(prediction.keys)), 1)
        rotated = prediction.X_macro.iloc[donors].set_axis(prediction.keys.index)
        variants.append(('monthly_rotation', rotated.assign(
            source_asof_date=prediction.keys.asof_date.iloc[donors].to_numpy())))
    if prior is not None and len(prior):
        variants.append(('lag_13_weeks', prior))
    if not variants:
        return None
    return pd.concat([_perturbation(model, prediction, context, truth, scores, fixed_scale, interactions, variant, donors)
                      for variant, donors in variants], ignore_index=True)


def _perturbation(model, prediction, context, truth, scores, fixed_scale, interactions, variant, donors):
    source = prediction.keys.loc[donors.index].assign(source_asof_date=donors.source_asof_date)
    lineage = model.macro_lineage
    groups = sorted({lineage[c] for c in prediction.X_macro if c in lineage})
    results = []
    for group in [*groups, 'all_macro']:
        columns = [c for c in prediction.X_macro if group == 'all_macro' or lineage.get(c) == group]
        macro = prediction.X_macro.copy()
        for column in columns:
            macro.loc[donors.index, column] = donors[column].array
        cross = getattr(prediction, 'X_interactions', None)
        if cross is not None:
            cross = cross.copy()
            for item in interactions:
                feature, macro_parent = item['feature'], item['macro_feature']
                if feature in cross and macro_parent in columns:
                    cross[feature] = macro[macro_parent] * prediction.X_market[item['market_feature']]
        inputs = pd.concat([prediction.X_market, macro, cross], axis=1)[prediction.feature_names]
        changes = ~(inputs.eq(prediction.X) | (inputs.isna() & prediction.X.isna()))
        changed_count = int(changes.any(axis=0).sum())
        replace_fields = dict(X=inputs, X_macro=macro)
        if cross is not None:
            replace_fields['X_interactions'] = cross
        shifted = replace(prediction, **replace_fields)
        xp = transform_inputs(model.preprocessor, shifted)
        alternative = score_predictions(model.predict(xp, context), context, truth, task=model.task, fixed_scale=fixed_scale)
        metrics = (['loss', 'brier'] if model.task == 'classification' else
            ['loss'] + ['squared_' + name for name in DIMENSIONS] + ['absolute_error_' + target for target in CORE])
        paired = scores[KEY + metrics].merge(alternative[KEY + metrics], on=KEY, validate='one_to_one',
                                            suffixes=('_real', '_perturbed'))
        paired = paired.merge(source, on=KEY, validate='one_to_one')
        results.append(paired.assign(group=group, perturbation=variant, changed_input_columns=changed_count))
    return pd.concat(results, ignore_index=True)
