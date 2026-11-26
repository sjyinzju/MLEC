"""Retrospective forest sensitivity of native out-of-sample predictions."""
from dataclasses import replace

import numpy as np
import pandas as pd

from ..common import CORE, KEY
from ..model_contract import DIMENSIONS, transform_inputs
from .scoring import score_predictions


def forest_perturbation_losses(model, prediction, context, truth, scores, *, fixed_scale, interactions):
    """Rotate this month's macro rows and rebuild their interactions against unchanged M."""
    if len(prediction.keys) < 2 or not len(prediction.X_macro.columns):
        return None
    donors = np.roll(np.arange(len(prediction.keys)), 1)
    source = prediction.keys.assign(source_asof_date=prediction.keys.asof_date.iloc[donors].to_numpy())
    lineage = model.macro_lineage
    groups = sorted({lineage[c] for c in prediction.X_macro if c in lineage})
    results = []
    for group in [*groups, 'all_macro']:
        columns = [c for c in prediction.X_macro if group == 'all_macro' or lineage.get(c) == group]
        macro = prediction.X_macro.copy()
        macro[columns] = macro[columns].iloc[donors].set_axis(macro.index)
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
        results.append(paired.assign(group=group, changed_input_columns=changed_count))
    return pd.concat(results, ignore_index=True)
