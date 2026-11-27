"""Isolated technical controls for direct and conditional macro learning."""
import numpy as np
import pandas as pd

from ..common import CORE
from ..framework import Dataset
from ..model_contract import (CONTRACT_VERSION, DIMENSIONS, IDENTITY, fit_context, fit_inputs,
                              prediction_context, transform_inputs)
from ..models.random_forest import FAMILY, RandomForestAdapter
from ..target_adapters import fit_targets
from .scoring import add_losses


MACRO = 'macro__simulation__known_signal'
FOLDS = ['2020-01', '2020-02', '2020-03', '2020-04', '2020-05', '2020-06']
PARAMETERS = dict(n_estimators=48, max_depth=8, min_samples_leaf=4, max_features=1.0, max_samples=1.0)
POLICY = dict(single_class='error', missing_class='zero_for_absent')
SEED = 3060


def synthetic_data(task, fold, role, variant, signal_type='direct'):
    rng = np.random.default_rng(SEED)
    dates = pd.Series(pd.date_range('2008-01-04', '2020-06-30', freq='W-FRI'))
    keys = pd.DataFrame(dict(market_id='000985.SH', asof_date=dates, horizon=20))
    asof = dates.dt.tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
    maturity = asof + pd.Timedelta(weeks=4)
    cutoff = pd.Timestamp(fold, tz='Asia/Shanghai') - pd.Timedelta(hours=6)
    keep = maturity.le(cutoff) if role == 'train' else dates.dt.strftime('%Y-%m').eq(fold)
    signal = rng.uniform(-2, 2, len(dates))
    regime = (rng.random(len(dates)) > .32).astype(float)
    noise = rng.normal(size=(len(dates), 3))
    market = pd.DataFrame(noise, columns=['market__simulation_noise_' + str(j) for j in range(3)])
    market['market__simulation_regime'] = regime
    market = market.loc[keep].reset_index(drop=True)
    macro = pd.DataFrame(index=market.index)
    if variant != 'M':
        donor = np.random.default_rng(SEED + (1 if role == 'train' else 2))
        selected = signal[keep]
        macro[MACRO] = donor.permutation(selected) if variant == 'shuffled' else selected
    # The sign reverses across a financial regime that has no standalone relation to y.
    latent = signal if signal_type == 'direct' else np.where(regime == 1, signal, -signal)
    if signal_type == 'weak':
        latent = .55 * signal + np.random.default_rng(5081).normal(0., .65, len(dates))
    if task == 'classification':
        outcomes = pd.DataFrame({'future_state_id': np.digitize(latent, [-.65, .65])})
    else:
        scales = [1., 1., 1., 1e-12, .05, 1., 1.]
        response = .25 + .07 * latent + .015 * latent**2
        outcomes = pd.DataFrame({c: scale * (response + .003 * rng.normal(size=len(dates)))
                                 for c, scale in zip(CORE, scales)})
    keys = keys.loc[keep].reset_index(drop=True)
    versions = {key: 'isolated-forest-simulation-v1' for key in IDENTITY}
    versions['contract_version'] = CONTRACT_VERSION
    meta = keys.assign(asof_time=asof[keep].reset_index(drop=True), fit_cutoff=cutoff, **versions)
    if role != 'prediction':
        meta['label_available_at'] = maturity[keep].reset_index(drop=True)
    features = pd.concat([market, macro], axis=1)
    info = 'M' if variant == 'M' else 'M+Z'
    schema = dict(class_ids=[0, 1, 2], dictionary_version=versions['dictionary_version'],
                  columns={'classification': ['future_state_id'], 'regression': CORE},
                  dimensions=DIMENSIONS, decision_rule='argmax in class order', continuous=[])
    feature_schema = dict(columns=list(features), dtypes=features.dtypes.astype(str).to_dict(), information_set=info)
    context = dict(market_id='000985.SH', fold_id=fold, role=role, view='formal', quality='isolated',
                   information_set=info, versions=versions)
    y = None if role == 'prediction' else outcomes.loc[keep].reset_index(drop=True)
    return Dataset(features, y, meta, list(features), keys, market, macro, feature_schema, schema, versions, context)


def synthetic_check(directory):
    rows = []
    variants = ('M', 'informed', 'shuffled')
    for signal, tasks in [('direct', ('classification', 'regression')),
                          ('conditional', ('classification', 'regression')), ('weak', ('classification',))]:
        for task in tasks:
            losses = {variant: [] for variant in variants}
            parameters = dict(PARAMETERS, class_weight=None, probability_alpha=.05) if task == 'classification' else PARAMETERS
            for variant in variants:
                for fold in FOLDS:
                    train, pred, truth = (synthetic_data(task, fold, role, variant, signal)
                                          for role in ('train', 'prediction', 'validation'))
                    pre, target = fit_inputs(train), fit_targets(train)
                    model = RandomForestAdapter(task=task, preprocessor=pre, target_adapter=target,
                        seed=SEED, parameters=parameters, training_keys=train.keys, policy=POLICY,
                        macro_lineage={MACRO: 'synthetic'})
                    model.fit(transform_inputs(pre, train), target.transform(train.y), fit_context(train))
                    xp = transform_inputs(pre, pred)
                    context = prediction_context(pred, pre, target, model_id=FAMILY,
                                                 model_version=model.model_version_, input_matrix=xp)
                    output = model.predict(xp, context)
                    fixed = dict(columns=CORE, scale=target.parameters_['scale']) if task == 'regression' else None
                    scored = add_losses(pd.concat([output, truth.y], axis=1), task, target.schema_, fixed)
                    losses[variant].extend(scored.loss.tolist())
                    if variant == 'informed' and fold == FOLDS[-1]:
                        package = directory / f'{signal}-{task}'
                        model.save(package)
                        reloaded = RandomForestAdapter.load(package)
                        pd.testing.assert_frame_equal(output, reloaded.predict(xp, context), check_exact=True)
                        assert model.diagnostic_artifact()['macro_split_count'] > 0
            means = {name: float(np.mean(values)) for name, values in losses.items()}
            ceiling = {'direct': .45, 'conditional': .65, 'weak': .98}[signal]
            passed = (means['informed'] < ceiling * min(means['M'], means['shuffled'])
                      and means['shuffled'] > .65 * means['M'])
            rows.append(dict(signal=signal, task=task, held_out_rows=len(losses['M']), losses=means,
                             informed_max_ratio=ceiling, shuffled_min_market_ratio=.65,
                             exact_prediction_after_reload=True, passed=passed))
    return dict(status='PASSED' if all(row['passed'] for row in rows) else 'FAILED',
                purpose='SMOKE_ONLY', real_market_data=False, seed=SEED, folds=FOLDS, summaries=rows,
                estimator_fit_calls=len(rows) * len(variants) * len(FOLDS))
