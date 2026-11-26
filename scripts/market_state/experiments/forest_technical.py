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
from .config import RF_INFORMATION, candidates, data_store, load_config
from .forest_acceptance import synthetic_check
from .portable import validate_source_receipt
from .runtime import environment, versions
from .technical import _TechnicalRunner


SOURCE_PROOF = ROOT / 'reports/market_state/model_io/test_results.json'
RECEIPT = ROOT / 'reports/model_build/random_forest/technical.json'


def acceptance_identity(config, store):
    identity = versions(config, store)
    identity.pop('config_hash')
    design = {name: config[name] for name in ['forest_design', 'search', 'policy', 'feature_extension']
              if name in config}
    return dict(identity, technical_design=digest(design), source_pytest_sha256=file_hash(SOURCE_PROOF))


def verify_forest_receipt(config, store):
    receipt = read_json(RECEIPT)
    if (receipt.get('status') != 'PASSED' or receipt.get('purpose') != 'SMOKE_ONLY' or
            receipt.get('identity') != acceptance_identity(config, store) or
            receipt.get('synthetic', {}).get('status') != 'PASSED' or
            len(receipt.get('real', [])) != 12):
        raise RuntimeError('A successful current isolated Random Forest technical receipt is required')
    return file_hash(RECEIPT)


def _real(config, store, directory):
    runner = _TechnicalRunner(config, store, directory, 1)
    items = []
    # Two markets and dates, all three information sets, both tasks.
    for market, fold in [('000985.SH', '2020-03'), ('000852.SH', '2022-04')]:
        for task in config['tasks']:
            parameters = candidates(config, task)[2]['parameters']
            common = dict(market=market, fold=fold, task=task, stage='development', mode='SMOKE_ONLY')
            for info in RF_INFORMATION:
                items.append((runner.task(**common, information=info, parameters=parameters,
                    seed=config['search']['screening_seed']), True))
            baselines = ['naive_history'] if task == 'classification' else ['naive_train_mean', 'naive_persistence']
            for family in baselines:
                items.append((runner.task(**common, information='M', parameters=config['baselines'],
                    seed=0, family=family), False))
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
            context = prediction_context(pred, pre, target, model_id='random_forest',
                model_version=model.model_version_, input_matrix=xp)
            predictions = pd.read_parquet(folder / 'predictions.parquet')
            pd.testing.assert_frame_equal(model.predict(xp, context), predictions, check_exact=True)
            columns = [c for c in predictions if c.startswith('predicted_') and c != 'predicted_state_id']
            if record['estimator_fit_calls'] != 1 or record['calibration_fit_calls'] != 0:
                raise RuntimeError('Expected one native forest and no probability calibrator')
            detail = read_json(folder / 'forest_diagnostics.json')
            if i['task'] == 'classification':
                ids = target.schema_['class_ids']
                if columns != ['predicted_state_prob_' + str(c) for c in ids]:
                    raise RuntimeError('Unexpected class probability order')
                np.testing.assert_allclose(predictions[columns].sum(axis=1), 1., atol=1e-12, rtol=0.)
                behavior = dict(train_class_support={str(int(k)):int(v) for k,v in train.y.future_state_id.value_counts().items()},
                    evaluation_class_support={str(int(k)):int(v) for k,v in scores.future_state_id.value_counts().items()},
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
                detail['development_perturbation_mean'] = changes.groupby('group').loss_increase.mean().to_dict()
            diagnostics.append(dict(market=i['market_id'], fold=i['fold_id'], task=i['task'],
                information_set=i['information_set'], score=float(scores.loss.mean()), mature_rows=len(scores),
                train_rows=len(x), input_columns=len(xp.columns), exact_save_reload=True,
                prediction_unique_counts={col: int(predictions[col].nunique()) for col in columns},
                estimator_fit_calls=record['estimator_fit_calls'], **behavior, forest=detail))
        if not any(d['information_set'] == 'M+Z_star' and d['forest']['macro_split_count'] for d in diagnostics):
            raise RuntimeError('Enhanced macro columns did not enter any real development split')
        for d in diagnostics:
            d['baseline_loss'] = matched[(d['market'], d['fold'], d['task'])]['baselines']
        return diagnostics
    finally:
        runner.scheduler.close()


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
            result['synthetic'] = synthetic_check(folder / 'synthetic')
            if result['synthetic']['status'] != 'PASSED':
                raise RuntimeError('Known macro signal was not recovered in all technical comparisons')
        result['status'] = 'PASSED'
    except Exception as error:
        result.update(status='FAILED', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        atomic_json(path, result)
    return result


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    result = run(execute=args.execute, data_root=args.data_root, destination=args.destination)
    print('FOREST_TECHNICAL_PASSED', len(result['real']), 'real development fits')
