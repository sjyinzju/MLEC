"""Development-only residual contrasts with a time-forward financial anchor."""
from dataclasses import replace

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from threadpoolctl import threadpool_limits

from ..common import CORE, KEY, digest
from ..framework import information_view
from ..model_contract import (fit_context, fit_inputs, key_hash, prediction_context, regression_output,
                              training_partition, transform_inputs, truth_hash)
from ..models.random_forest import FAMILY, RandomForestAdapter
from ..target_adapters import fit_targets
from .scoring import score_predictions


LAMBDAS = (0., .25, .5, 1.)
CORRECTION = dict(n_estimators=96, max_depth=3, min_samples_leaf=16, max_features=.7, max_samples=.75)
START_YEAR = 2017
GROUPS = ('growth', 'prices', 'credit', 'rates', 'external')
PURE = 'M+Z_star_without_interactions'


def _view(dataset, information, store):
    if information != PURE:
        return information_view(dataset, information, store=store)
    inputs = pd.concat([dataset.X_market, dataset.X_macro], axis=1)
    columns = inputs.columns.tolist()
    return replace(dataset, X=inputs, X_interactions=None, feature_names=columns,
                   feature_schema=dict(columns=columns, dtypes=inputs.dtypes.astype(str).to_dict(),
                                       information_set=information),
                   context=dict(dataset.context, information_set=information))


class FinancialResiduals:
    def __init__(self, parameters, seed, policy):
        self.parameters, self.seed, self.policy = parameters, seed, policy
        self.cache = {}
        self.inner_fits = 0

    def _oof(self, parent):
        dates = parent.keys.asof_date
        frames, provenance = [], []
        for start in pd.date_range(f'{START_YEAR}-01-01', dates.max(), freq='6MS'):
            end = start + pd.DateOffset(months=6)
            cutoff = start.tz_localize('Asia/Shanghai') - pd.Timedelta(hours=6)
            mature = parent.metadata.label_available_at.le(cutoff) & parent.metadata.asof_time.le(cutoff)
            holdout = dates.ge(start) & dates.lt(end)
            if not holdout.any():
                continue
            inner = training_partition(parent, parent.keys[mature], role='train', fit_cutoff=cutoff)
            valid = training_partition(parent, parent.keys[holdout], role='validation', fit_cutoff=cutoff)
            ctx = fit_context(inner)
            identity = digest([ctx.market_id, ctx.versions, ctx.fit_cutoff, ctx.training_keys_hash,
                               ctx.training_target_hash, parent.context['quality'], key_hash(valid.keys)])
            if identity not in self.cache:
                pre, target = fit_inputs(inner), fit_targets(inner)
                model = RandomForestAdapter(task='regression', preprocessor=pre, target_adapter=target,
                    training_keys=inner.keys, parameters=self.parameters, seed=self.seed, policy=self.policy)
                model.fit(transform_inputs(pre, inner), target.transform(inner.y), ctx)
                values = model.regression_values(transform_inputs(pre, valid))
                self.inner_fits += len(model.diagnostics_)
                self.cache[identity] = values
            frames.append(pd.concat([valid.keys, self.cache[identity]], axis=1))
            provenance.append(dict(inner_cutoff=str(cutoff), first_prediction=str(valid.metadata.asof_time.min()),
                latest_anchor_train_label=str(inner.metadata.label_available_at.max()),
                latest_residual_label=str(valid.metadata.label_available_at.max()),
                training_keys_hash=ctx.training_keys_hash, validation_keys_hash=key_hash(valid.keys),
                validation_rows=len(valid.keys)))
        return pd.concat(frames, ignore_index=True), provenance

    def evaluate(self, broad_train, broad_prediction, original_train, original_prediction, truth, original_truth,
                 anchor_forecast, anchor_scores, store, fixed_scale):
        """Learn each correction on the same residual membership and score identical weeks."""
        anchor_train = _view(broad_train, 'M', store)
        oof, provenance = self._oof(anchor_train)
        cutoff = broad_train.metadata.fit_cutoff.iloc[0]
        oof_keys = oof[KEY]
        residual_train = training_partition(broad_train, oof_keys, role='train', fit_cutoff=cutoff)
        original_residual_train = training_partition(original_train, oof_keys, role='train', fit_cutoff=cutoff)
        pd.testing.assert_frame_equal(oof_keys, residual_train.keys, check_exact=True)
        pd.testing.assert_frame_equal(residual_train.y, original_residual_train.y, check_exact=True)
        target = fit_targets(residual_train)
        residual = target.transform(residual_train.y) - target.transform(oof[CORE])
        if any(ds.context['role'] != 'validation' for ds in (truth, original_truth)):
            raise ValueError('Residual mechanism is evaluated on the registered development reads only')
        pd.testing.assert_frame_equal(truth.keys, original_truth.keys, check_exact=True)
        pd.testing.assert_frame_equal(truth.y, original_truth.y, check_exact=True)
        base = anchor_forecast[KEY + ['predicted_' + c for c in CORE]].rename(
            columns={'predicted_' + c: c for c in CORE})
        keyed = broad_prediction.keys.merge(base, on=KEY, how='left', validate='one_to_one')
        if keyed[CORE].isna().any().any():
            raise ValueError('M anchor must predict every outer development feature row')
        evidence = []
        for information in ['M', 'M+Z', 'M+Z_star', PURE] + ['M+Z_star_' + group for group in GROUPS]:
            if information == 'M+Z':
                train, pred = original_residual_train, original_prediction
                scoring_truth = original_truth
            else:
                train = _view(residual_train, information, store)
                pred = _view(broad_prediction, information, store)
                scoring_truth = _view(truth, information, store)
            pre = fit_inputs(train)
            x, xp = transform_inputs(pre, train), transform_inputs(pre, pred)
            model = RandomForestRegressor(**CORRECTION, bootstrap=True, random_state=self.seed, n_jobs=1)
            with threadpool_limits(limits=1):
                model.fit(x, residual)
                shift = model.predict(xp) * np.asarray(target.parameters_['scale']) / np.asarray(target.parameters_['weight'])
            for strength in LAMBDAS:
                values = keyed[CORE].copy() if strength == 0 else keyed[CORE] + strength * shift
                identity = digest(dict(anchor=anchor_scores.model_version.iloc[0], parameters=CORRECTION,
                    residual_truth=truth_hash(train.y), residual_keys=key_hash(train.keys), information=information,
                    strength=strength, seed=self.seed, blocks=provenance))
                ctx = prediction_context(pred, pre, target, model_id=FAMILY, model_version=identity, input_matrix=xp)
                scores = score_predictions(regression_output(ctx, values, target.schema_), ctx, scoring_truth,
                                           task='regression', fixed_scale=fixed_scale)
                if strength == 0:
                    if not scores[KEY].equals(anchor_scores[KEY]):
                        raise ValueError('Residual correction changed the anchor scoring keys')
                    paired = scores[KEY + ['loss']].merge(anchor_scores[KEY + ['loss']], on=KEY,
                                                          validate='one_to_one', suffixes=('', '_anchor'))
                    np.testing.assert_array_equal(paired.loss, paired.loss_anchor)
                    np.testing.assert_array_equal(values, keyed[CORE])
                evidence.append(scores.assign(correction=information, strength=strength))
        return pd.concat(evidence, ignore_index=True), provenance
