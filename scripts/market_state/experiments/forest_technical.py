"""Bounded explicit RF acceptance through the normal scheduler and fit runner."""
from argparse import ArgumentParser
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ..common import CORE, KEY, ROOT, digest
from ..framework import load_dataset
from ..interface_acceptance import assert_interface_accepted
from ..model_contract import prediction_context
from ..models.random_forest import RandomForestAdapter
from ..release import file_hash
from .artifacts import atomic_json, native_path, read_json
from .config import RF_INFORMATION, candidates, data_store, load_config, portable_config
from .forest_acceptance import synthetic_check
from .forest_reporting import probability_metrics
from .forest_selection import probability_grid
from .portable import validate_source_receipt
from .runtime import environment, versions
from .technical import _TechnicalRunner


SOURCE_PROOF = ROOT / 'reports/market_state/model_io/test_results.json'
RECEIPT = ROOT / 'reports/model_build/random_forest/technical.json'
SMOKE_RECEIPT = ROOT / 'reports/model_build/random_forest/smoke.json'


def acceptance_identity(config, store):
    identity = versions(config, store)
    identity.pop('config_hash')
    design = portable_config(config)
    design.pop('resources')
    return dict(identity, technical_design=digest(design), source_pytest_sha256=file_hash(SOURCE_PROOF))


def verify_forest_receipt(config, store):
    receipt = read_json(RECEIPT)
    if (receipt.get('status') != 'PASSED' or receipt.get('purpose') != 'SMOKE_ONLY' or
            receipt.get('identity') != acceptance_identity(config, store) or
            receipt.get('synthetic', {}).get('status') != 'PASSED' or
            len(receipt.get('real', [])) != 13 or not receipt.get('replay', {}).get('exact_save_reload')):
        raise RuntimeError('A successful current isolated Random Forest technical receipt is required')
    return file_hash(RECEIPT)


def _real(config, store, directory, *, quick=False):
    runner = _TechnicalRunner(config, store, directory, 1)
    items = []
    # Two markets and dates, all three information sets, both tasks.
    cohorts = [('000852.SH', '2022-04')] if quick else [('000985.SH', '2020-03'), ('000852.SH', '2022-04')]
    for market, fold in cohorts:
        for task in config['tasks']:
            parameters = candidates(config, task)[2]['parameters']
            if task == 'classification':
                parameters = dict(parameters, probability_alpha=.1)
            common = dict(market=market, fold=fold, task=task, stage='development', mode='SMOKE_ONLY')
            for info in RF_INFORMATION:
                items.append((runner.task(**common, information=info, parameters=parameters,
                    seed=config['search']['screening_seed']), True))
            baselines = ['naive_history'] if task == 'classification' else ['naive_train_mean', 'naive_persistence']
            for family in baselines:
                items.append((runner.task(**common, information='M', parameters=config['baselines'],
                    seed=0, family=family), False))
            if (market, task) == ('000852.SH', 'regression') and not quick:
                alternative = 'native' if parameters['regression_architecture'] == 'independent' else 'independent'
                items.append((runner.task(**common, information='M+Z_star',
                    parameters=dict(parameters, regression_architecture=alternative), seed=3060), True))
    try:
        records = runner.scheduler.map(items)
        diagnostics = []
        matched = {}
        for (task, retain), record in zip(items, records):
            i = task['identity']
            folder = runner.root / record['artifact']
            scores = pd.read_parquet(folder / 'losses.parquet')
            if not len(scores) or not np.isfinite(scores.loss).all():
                raise RuntimeError('Technical example is missing eligible mature scoring rows')
            truth = ['future_state_id'] if i['task'] == 'classification' else CORE
            key = (i['market_id'], i['fold_id'], i['task'])
            reference = matched.setdefault(key, dict(keys=scores[KEY + truth].copy(), baselines={}))
            pd.testing.assert_frame_equal(reference['keys'], scores[KEY + truth], check_exact=True)
            if not retain:
                reference['baselines'][i['family']] = float(scores.loss.mean())
                continue
            model = RandomForestAdapter.load(folder / 'model_package')
            train, pre, target, pred, x, xp = runner.executor.matrices(task)
            financial = train.X_market.columns.to_list()
            common_columns = [c for c in x if c.removeprefix('missing__') in financial]
            time_and_market = (train.metadata[['asof_time', 'label_available_at', 'fit_cutoff']],
                               train.X_market, pred.X_market, x[common_columns], xp[common_columns])
            reference.setdefault('time_and_market', time_and_market)
            for expected_block, actual_block in zip(reference['time_and_market'], time_and_market):
                pd.testing.assert_frame_equal(expected_block, actual_block, check_exact=True)
            context = prediction_context(pred, pre, target, model_id='random_forest',
                model_version=model.model_version_, input_matrix=xp)
            predictions = pd.read_parquet(folder / 'predictions.parquet')
            pd.testing.assert_frame_equal(model.predict(xp, context), predictions, check_exact=True)
            columns = [c for c in predictions if c.startswith('predicted_') and c != 'predicted_state_id']
            expected = 7 if i['parameters'].get('regression_architecture') == 'independent' else 1
            if record['estimator_fit_calls'] != expected or record['calibration_fit_calls'] != 0:
                raise RuntimeError('Unexpected forest or probability calibrator fit count')
            detail = read_json(folder / 'forest_diagnostics.json')
            if i['task'] == 'classification':
                ids = target.schema_['class_ids']
                if columns != ['predicted_state_prob_' + str(c) for c in ids]:
                    raise RuntimeError('Unexpected class probability order')
                np.testing.assert_allclose(predictions[columns].sum(axis=1), 1., atol=1e-12, rtol=0.)
                if (predictions[columns] <= 0.).any().any():
                    raise RuntimeError('Stabilized classifier assigned zero probability')
                counts = train.y.future_state_id.value_counts().reindex(ids, fill_value=0)
                expected_prior = (counts.to_numpy() + 1.) / (len(train.y) + len(ids))
                np.testing.assert_array_equal(model.training_prior_, expected_prior)
                probability = pd.read_parquet(folder / 'probability_evidence.parquet').dropna(subset=['observed_state_id'])
                native = probability_grid(probability, ids, [0.])[0][1]
                behavior = dict(train_class_support={str(int(k)):int(v) for k,v in train.y.future_state_id.value_counts().items()},
                    evaluation_class_support={str(int(k)):int(v) for k,v in scores.future_state_id.value_counts().items()},
                    native_log_loss=float(native.log_loss.mean()), native_brier=float(native.brier.mean()),
                    brier=float(scores.brier.mean()),
                    exact_zero_probability=int(predictions[columns].eq(0).to_numpy().sum()))
            else:
                if columns != ['predicted_' + c for c in CORE]:
                    raise RuntimeError('Unexpected seven-target order')
                behavior = dict(target_rmse={c: float(np.sqrt(scores['squared_error_' + c].mean())) for c in CORE},
                    economic_boundary_rows=int(scores.economic_bound_violations.ne('[]').sum()))
            shifts = folder / 'perturbed_losses.parquet'
            if shifts.is_file():
                changes = pd.read_parquet(shifts)
                changes['loss_increase'] = changes.loss_perturbed - changes.loss_real
                detail['development_perturbation_mean'] = {
                    name: part.groupby('group').loss_increase.mean().to_dict()
                    for name, part in changes.groupby('perturbation')}
            diagnostics.append(dict(market=i['market_id'], fold=i['fold_id'], task=i['task'],
                information_set=i['information_set'], parameters=i['parameters'], score=float(scores.loss.mean()), mature_rows=len(scores),
                train_rows=len(x), input_columns=len(xp.columns), exact_save_reload=True, exact_financial_inputs=True,
                prediction_unique_counts={col: int(predictions[col].nunique()) for col in columns},
                estimator_fit_calls=record['estimator_fit_calls'], **behavior, forest=detail))
        if not any(d['information_set'] == 'M+Z_star' and d['forest']['macro_split_count'] for d in diagnostics):
            raise RuntimeError('Enhanced macro columns did not enter any real development split')
        for d in diagnostics:
            d['baseline_loss'] = matched[(d['market'], d['fold'], d['task'])]['baselines']
        return diagnostics
    finally:
        runner.scheduler.close()


def replay_check(config, store, directory):
    runner = _TechnicalRunner(config, store, directory, 1)
    raw = candidates(config, 'classification')[4]['parameters']
    common = dict(market='000300.SH', task='classification', information='M+Z_star', seed=3060,
                  fold='2022-04', stage='development')
    screened = runner.task(**common, mode='search', parameters=raw)
    stabilized = runner.task(**common, mode='replay_smoke', parameters=dict(raw, probability_alpha=.1))
    try:
        first = runner.monthly(screened, save_package=True)
        second = runner.monthly(stabilized, save_package=True)
        resumed = runner.monthly(stabilized, save_package=True)
        folder = runner.root / second['artifact']
        source = read_json(runner.root / first['artifact'] / 'context.json')
        replay = read_json(folder / 'context.json')
        if (first['estimator_fit_calls'], second['estimator_fit_calls'], replay['replayed_forest_fit_id']) != (1, 0, first['fit_id']):
            raise RuntimeError('Stabilized replay did not reuse the exact native fit')
        if resumed != second or source['forest_weights_version'] != replay['forest_weights_version']:
            raise RuntimeError('Replayed forest was changed on restart')
        model = RandomForestAdapter.load(folder / 'model_package')
        _, pre, target, prediction, _, matrix = runner.executor.matrices(stabilized)
        context = prediction_context(prediction, pre, target, model_id='random_forest',
                                     model_version=model.model_version_, input_matrix=matrix)
        pd.testing.assert_frame_equal(model.predict(matrix, context), pd.read_parquet(folder / 'predictions.parquet'),
                                      check_exact=True)
        return dict(source_fit=first['fit_id'], stabilized_fit=second['fit_id'], refits=0,
                    resumed_same_artifact=True, exact_save_reload=True)
    finally:
        runner.scheduler.close()


def weight_comparison(config, store, directory):
    runner = _TechnicalRunner(config, store, directory, 2)
    parameters = candidates(config, 'classification')[17]['parameters']
    cases = [(runner.task(market='000300.SH', fold=fold, task='classification', information='M+Z_star',
            stage='development', mode='class_weight_comparison', seed=seed,
            parameters=dict(parameters, class_weight=weight, probability_alpha=.1)), False)
        for fold in ('2020-03', '2020-08', '2021-09', '2022-04', '2022-11')
        for seed in (3060, 3061) for weight in (None, 'balanced')]
    try:
        rows = []
        for (task, _), record in zip(cases, runner.scheduler.map(cases)):
            i = task['identity']
            p = pd.read_parquet(runner.root / record['artifact'] / 'probability_evidence.parquet')
            rows.append(p.assign(seed=i['seed'], class_weight=i['parameters']['class_weight'] or 'natural'))
        output = []
        keys = ['seed', 'class_weight']
        for values, part in pd.concat(rows).groupby(keys):
            for source in ['native', 'stabilized']:
                total, details = probability_metrics(part, store.target_schema(),
                    'native_state_prob_' if source == 'native' else 'predicted_state_prob_')
                output.extend(dict(zip(keys, values), source=source, log_loss=total['log_loss'],
                                   brier=total['brier'], observed_floor_hits=total['log_floor_hits'], **row)
                              for row in details)
        return output
    finally:
        runner.scheduler.close()


def smoke(*, execute, config, data_root=None):
    if not execute:
        print('SMOKE_ONLY planned: all three information sets, two tasks, one development month and a fit replay')
        return
    store = data_store(config, data_root or ROOT / config['data_root'])
    assert_interface_accepted(data_root=store.root, feature_extension='z_star')
    validate_source_receipt(read_json(SOURCE_PROOF))
    receipt = dict(purpose='SMOKE_ONLY', identity=acceptance_identity(config, store), formal_fit_calls=0,
                   environment=environment(), status='STARTED')
    dst = ROOT / 'runtime_acceptance/forest_smoke.json' if (ROOT / 'package.manifest.json').exists() else SMOKE_RECEIPT
    try:
        with tempfile.TemporaryDirectory(prefix='rf-smoke-', dir=native_path(tempfile.gettempdir())) as tmp:
            folder = Path(tmp)
            receipt['real'] = _real(config, store, folder / 'main', quick=True)
            receipt['replay'] = replay_check(config, store, folder / 'replay')
        receipt['status'] = 'PASSED'
    except Exception as error:
        receipt.update(status='FAILED', error=str(error))
        raise
    finally:
        atomic_json(dst, receipt)
    print('FOREST_SMOKE_PASSED', len(receipt['real']), 'development fits and native-weight replay')
    return receipt


def run(*, execute, data_root=None, destination=None):
    if not execute:
        raise ValueError('Explicit --execute is required for bounded real and synthetic fitting')
    config = load_config(ROOT / 'config/experiments/random_forest.yaml')
    config['data_root'] = str(Path(data_root).resolve() if data_root else ROOT / config['data_root'])
    store = data_store(config)
    assert_interface_accepted(data_root=store.root, feature_extension='z_star')
    validate_source_receipt(read_json(SOURCE_PROOF))
    result = dict(status='STARTED', purpose='SMOKE_ONLY', identity=acceptance_identity(config, store),
        environment=environment(), formal_fit_calls=0)
    path = destination or (ROOT / 'runtime_acceptance/forest_technical.json' if (ROOT / 'package.manifest.json').exists() else RECEIPT)
    try:
        with tempfile.TemporaryDirectory(prefix='mlec-rf-', dir=native_path(tempfile.gettempdir())) as tmp:
            folder = Path(tmp)
            result['real'] = _real(config, store, folder / 'real')
            result['replay'] = replay_check(config, store, folder / 'replay')
            result['class_weight_comparison'] = weight_comparison(config, store, folder / 'weights')
            result['synthetic'] = synthetic_check(folder / 'synthetic')
            if result['synthetic']['status'] != 'PASSED':
                raise RuntimeError('Known macro signal was not recovered in all technical comparisons')
        result['status'] = 'PASSED'
    except Exception as error:
        result.update(status='FAILED', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        atomic_json(path, result)
    if not (ROOT / 'package.manifest.json').exists() and path == RECEIPT:
        evidence = ROOT / 'reports/model_build/random_forest/final_optimization'
        evidence.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(result['class_weight_comparison']).to_csv(evidence / 'class_weight_comparison.csv', index=False)
    return result


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    result = run(execute=args.execute, data_root=args.data_root, destination=args.destination)
    print('FOREST_TECHNICAL_PASSED', len(result['real']), 'real development fits')
