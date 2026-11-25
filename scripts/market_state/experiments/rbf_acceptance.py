"""Explicit RBF acceptance: matched real runner probes and isolated signal control."""
from argparse import ArgumentParser
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import numpy as np
import pandas as pd
from ..common import CORE, ROOT, digest
from ..framework import DataStore, Dataset
from ..model_contract import (CONTRACT_VERSION, DIMENSIONS, IDENTITY, fit_context, fit_inputs,
    prediction_context, transform_inputs)
from ..models.rbf_svm import RBFSVMAdapter
from ..models.training import TrainingPartitions
from ..release import file_hash
from ..target_adapters import fit_targets
from .artifacts import atomic_json, atomic_parquet, native_path, read_json
from .config import load_config
from .rbf_diagnostics import vintage_audit
from .runtime import preflight, versions
from .scoring import add_losses
from .technical import _batch

CONFIG = ROOT / 'config/experiments/rbf_macro_learning_20261125.yaml'
CONTROL = dict(seeds=[3059, 3060], test_months=['2020-01', '2020-02', '2020-03', '2020-04'],
    thresholds={'classification': .75, 'regression': .40}, shuffled_minimum_relative_to_M=.80)


def receipt_path():
    return ROOT / 'reports/model_build/rbf_svm/macro_20261125/technical.json'


def verify_receipt(result, identity):
    if (result.get('status') != 'PASSED' or result.get('versions') != identity or result.get('purpose') != 'SMOKE_ONLY'
            or result.get('synthetic', {}).get('design') != CONTROL or len(result.get('matched_real', [])) != 2):
        raise RuntimeError('Complete the current weighted RBF real and synthetic acceptance before formal B/C')


def _parameters(config, task, *, weight=.5, representation='compact', eta=.25, calibrator='shrinkage'):
    base = dict(C=4. if task == 'classification' else 8., gamma_factor=eta,
        tol=config['search']['tol'], max_iter=config['search']['max_iter'],
        macro_weight=weight, representation=representation, geometry_version=config['rbf_design']['version'])
    return dict(base, calibrator=calibrator, class_weight=None) if task == 'classification' else dict(base, epsilon=.12)


def _synthetic_data(seed, task, fold, role, variant):
    rng = np.random.default_rng(seed)
    date = pd.Series(pd.date_range('2015-01-09', '2020-04-30', freq='W-FRI'))
    key = pd.DataFrame(dict(market_id='000985.SH', asof_date=date, horizon=20))
    asof = date.dt.tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
    maturity = asof + pd.Timedelta(weeks=4)
    cutoff = (pd.Timestamp(fold) - pd.Timedelta(days=1)).tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
    use = maturity.le(cutoff) if role == 'train' else date.dt.strftime('%Y-%m').eq(fold)
    identity = {k: 'synthetic-isolated-' + str(seed) for k in IDENTITY}
    identity['contract_version'] = CONTRACT_VERSION
    m = pd.DataFrame(rng.normal(size=(len(date), 6)), columns=['market__control_' + str(j) for j in range(6)])
    signal = rng.uniform(-2, 2, size=len(date))
    # The market noise is independent of both targets; only macro has signal.
    z = signal[use].copy()
    if variant == 'shuffled':
        z = np.random.default_rng(seed + (101 if role == 'train' else 202)).permutation(z)
    macro = pd.DataFrame({'macro__known_signal__latest': z}) if variant != 'M' else pd.DataFrame(index=range(int(use.sum())))
    m = m.loc[use].reset_index(drop=True)
    if task == 'classification':
        target = pd.DataFrame(dict(future_state_id=np.digitize(signal, [-.6, .6]))).loc[use].reset_index(drop=True)
    else:
        response = .25 + .06 * signal + .02 * signal**2
        target = pd.DataFrame({c: response * scale + rng.normal(0, .004 * scale, len(date))
            for c, scale in zip(CORE, [1., 1., 1., 1e-12, .05, 1., 1.])}).loc[use].reset_index(drop=True)
    keys = key.loc[use].reset_index(drop=True)
    metadata = keys.assign(asof_time=asof[use].reset_index(drop=True), fit_cutoff=cutoff, **identity)
    if role != 'prediction':
        metadata['label_available_at'] = maturity[use].reset_index(drop=True)
    features = pd.concat([m, macro], axis=1)
    information = 'M' if variant == 'M' else 'M+Z'
    schema = dict(class_ids=[0, 1, 2], dictionary_version=identity['dictionary_version'],
        columns={'classification': ['future_state_id'], 'regression': CORE}, dimensions=DIMENSIONS,
        decision_rule='argmax in class order', continuous=[])
    return Dataset(features, None if role == 'prediction' else target, metadata, list(features), keys, m, macro,
        dict(columns=list(features), dtypes=features.dtypes.astype(str).to_dict()), schema, identity,
        dict(market_id='000985.SH', fold_id=fold, role=role, view='formal', quality='isolated',
            information_set=information, versions=identity))


def synthetic(config, directory):
    records, summaries = [], []
    for seed in CONTROL['seeds']:
        for task in ['classification', 'regression']:
            for variant in ['M', 'macro', 'shuffled']:
                for month in CONTROL['test_months']:
                    train, future, truth = (_synthetic_data(seed, task, month, role, variant)
                        for role in ['train', 'prediction', 'validation'])
                    pre, target = fit_inputs(train), fit_targets(train)
                    parameters = _parameters(config, task, weight=0. if variant == 'M' else .5)
                    model = RBFSVMAdapter(task=task, preprocessor=pre, target_adapter=target, seed=seed,
                        parameters=parameters, training_keys=train.keys, solver=config['solver'], policy=config['policy'],
                        calibration=config['calibration'], training_service=TrainingPartitions(train) if task == 'classification' else None,
                        macro_lineage={'macro__known_signal__latest': 'synthetic'})
                    X, Xp = transform_inputs(pre, train), transform_inputs(pre, future)
                    model.fit(X, target.transform(train.y), fit_context(train))
                    context = prediction_context(future, pre, target, model_id='rbf_svm', model_version=model.model_version_, input_matrix=Xp)
                    output = model.predict(Xp, context)
                    fixed = dict(columns=CORE, scale=target.parameters_['scale']) if task == 'regression' else None
                    scored = add_losses(pd.concat([output, truth.y], axis=1), task, train.target_schema, fixed)
                    records.append(scored[['market_id', 'asof_date', 'horizon', 'loss']].assign(seed=seed, task=task, variant=variant))
                    if month == CONTROL['test_months'][-1]:
                        package = directory / f'{seed}-{task}-{variant}'
                        model.save(package)
                        pd.testing.assert_frame_equal(RBFSVMAdapter.load(package).predict(Xp, context), output, check_exact=True)
            frame = pd.concat(records[-3 * len(CONTROL['test_months']):], ignore_index=True)
            losses = frame.groupby('variant').loss.mean().to_dict()
            ratio = CONTROL['thresholds'][task]
            passed = (losses['macro'] <= ratio * min(losses['M'], losses['shuffled'])
                and losses['shuffled'] >= CONTROL['shuffled_minimum_relative_to_M'] * losses['M'])
            summaries.append(dict(seed=seed, task=task, rows_per_variant=int(len(frame) / 3),
                loss=losses, exact_reload=True, passed=bool(passed)))
    return dict(design=CONTROL, summaries=summaries, passed=all(r['passed'] for r in summaries)), pd.concat(records)


def real_check(config, store, directory, cpus):
    design = []
    for task, market, fold, info in [('classification', '000300.SH', '2022-06', 'M+Z'), ('regression', '000905.SH', '2021-10', 'M+Z_credit')]:
        modern = _parameters(config, task, weight=.5, eta=.1, calibrator='platt')
        legacy = {k: v for k, v in modern.items() if k in ['C', 'tol', 'max_iter', 'gamma_factor', 'epsilon']}
        for information, parameters in [(info, legacy), (info, modern), ('M', dict(modern, macro_weight=0.)),
            (info, dict(modern, macro_weight=0.))]:
            design.append(dict(market=market, fold=fold, task=task, information=information, parameters=parameters))
    serial, predicted, scored = _batch(config, store, directory / 'serial', 1, design)
    parallel, parallel_predicted, _ = _batch(config, store, directory / 'process', cpus, design)
    receipt = []
    for first in [0, 4]:
        checks = serial['checks'][first:first + 4]
        p = [frame.filter(regex='^predicted_').to_numpy() for frame in predicted[first:first + 4]]
        loss = [float(frame.loss.mean()) for frame in scored[first:first + 4]]
        for a, b in zip(predicted[first:first + 4], parallel_predicted[first:first + 4]):
            pd.testing.assert_frame_equal(a, b, check_exact=True)
        np.testing.assert_array_equal(p[2], p[3])
        for row in checks[1]['kernel']['calibration_plan']:
            if row['status'] == 'ACCEPTED':
                assert pd.Timestamp(row['latest_train_label']) <= pd.Timestamp(row['fit_cutoff'])
                assert row['geometry_hash'] and row['preprocessing_content_hash']
        fit = next(d for d in (directory / 'serial/development/fits').iterdir()
            if read_json(d / 'context.json')['prediction']['model_version'] == checks[1]['model_version'])
        detail = read_json(fit / 'kernel_diagnostics.json')
        assert detail['matched_kernel']['train_train']['zero_weight_kernel_rms_change'] > 0
        assert detail['matched_kernel']['prediction_train']['legacy_kernel_rms_change'] > 0
        receipt.append(dict(task=checks[0]['task'], market=checks[0]['market_id'], fold=checks[0]['fold_id'],
            information_set=checks[0]['information_set'], validation_rows=len(scored[first]),
            loss_legacy=loss[0], loss_weighted=loss[1], loss_zero_weight=loss[3],
            zero_weight_exact_M=True, serial_spawn_exact=True, save_load_exact=True, matched_kernel=detail['matched_kernel'],
            actual_gamma_legacy=checks[0]['kernel']['actual_gamma'], actual_gamma_weighted=detail['actual_gamma'],
            training_keys=read_json(fit / 'context.json')['fit']['training_keys_hash'],
            model_artifact=fit.relative_to(directory / 'serial').as_posix(), code_bound_packages=True))
    return receipt, dict(serial=serial['elapsed_seconds'], parallel=parallel['elapsed_seconds'],
        serial_fit_calls=serial['estimator_fit_calls'], parallel_fit_calls=parallel['estimator_fit_calls'],
        serial_calibration_calls=serial['calibration_fit_calls'], parallel_calibration_calls=parallel['calibration_fit_calls'],
        resume_verified=True, workers=cpus)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--assets', type=Path, default=ROOT / 'results/rbf_macro_technical')
    parser.add_argument('--cpu-workers', type=int, default=2)
    args = parser.parse_args()
    if not args.execute:
        parser.error('Use --execute to authorize real solver checks')
    config = load_config(args.config)
    config['data_root'] = str((args.data_root or ROOT / config['data_root']).resolve())
    config['output_root'] = str(args.assets.resolve().parent)
    store = DataStore(config['data_root'])
    record = dict(purpose='SMOKE_ONLY', versions=versions(config, store), status='STARTED',
        commands=['python -m compileall -q scripts/market_state', 'python -m scripts.market_state.run interface-preflight',
            'python -m pytest -q', 'python -m scripts.market_state.experiments.rbf_acceptance --execute'],
        source_config=str(args.config.resolve()), config_sha256=file_hash(args.config),
        source_test_receipt_sha256=file_hash(ROOT / 'reports/market_state/model_io/test_results.json'))
    try:
        accepted = preflight(config, store, 'full')
        directory = native_path(args.assets.resolve() / (digest(record['versions'])[:16]))
        directory.mkdir(parents=True, exist_ok=True)
        record.update(dependency_versions=accepted['environment'], assets=str(directory))
        vintages = vintage_audit(store, config['quality'])
        assert all(row['effective_release_after_asof'] == 0 for row in vintages)
        atomic_json(directory / 'data_vintages.json', vintages)
        with TemporaryDirectory(dir=directory, prefix='control-') as temp:
            record['synthetic'], frame = synthetic(config, Path(temp))
            atomic_parquet(directory / 'synthetic_weekly.parquet', frame)
        if not record['synthetic']['passed']:
            raise RuntimeError('Known-signal control did not meet preregistered thresholds')
        record['matched_real'], record['runtime'] = real_check(config, store, directory, args.cpu_workers)
        record['files'] = {name: file_hash(directory / name) for name in ['data_vintages.json', 'synthetic_weekly.parquet']}
        record['status'] = 'PASSED'
    except BaseException as error:
        record.update(status='FAILED', error=f'{type(error).__name__}: {error}')
        atomic_json(receipt_path(), record)
        raise
    atomic_json(receipt_path(), record)
    print(json.dumps(dict(status=record['status'], receipt=str(receipt_path()), assets=record['assets']), ensure_ascii=False))


if __name__ == '__main__':
    main()
