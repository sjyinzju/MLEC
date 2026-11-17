"""Optional real fit connectivity check. Never called by tests, preflight or pipeline."""
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
from ..common import ROOT, digest
from ..framework import DataStore
from ..interface_acceptance import assert_interface_accepted
from ..models.elastic_net import ElasticNetAdapter
from .config import load_config
from .artifacts import read_json, atomic_json
from .runtime import MonthlyExecutor, versions, environment


def smoke(args):
    smoke_config = read_json(args.config)
    if smoke_config.get('purpose') != 'SMOKE_ONLY':
        raise ValueError('smoke requires the isolated SMOKE_ONLY configuration')
    if not args.execute:
        print('SMOKE_ONLY planned: 1 market, 1 month, 2 tasks x M/M+Z; no fit without --execute')
        return
    config = load_config()
    config.update(purpose='SMOKE_ONLY', data_root=str(args.data_root or ROOT / smoke_config['data_root']))
    config['resources']['threads_per_task'] = args.cpu_threads or smoke_config['threads_per_task']
    environment()
    store = DataStore(config['data_root'])
    assert_interface_accepted(data_root=store.root)
    identity = versions(config, store)
    executor = MonthlyExecutor(config, store, identity)
    checks = []
    with tempfile.TemporaryDirectory(prefix='mlec-smoke-') as directory:
        for target in ['classification', 'regression']:
            for info in ['M', 'M+Z']:
                task = dict(identity=dict(family='elastic_net', task=target, market_id=smoke_config['market'],
                    information_set=info, mode='SMOKE_ONLY', stage='development', fold_id=smoke_config['fold'],
                    parameters=smoke_config['parameters'][target], seed=smoke_config['seed'], backend='cpu',
                    versions=identity, purpose='SMOKE_ONLY'))
                output = Path(directory) / (target + info.replace('+', '_'))
                output.mkdir()
                executor(task, output, save_package=True)
                loaded = ElasticNetAdapter.load(output / 'model_package')
                train, pre, adapter, prediction = executor.prepare(task)
                from ..model_contract import transform_inputs, prediction_context
                context = prediction_context(prediction, pre, adapter, model_id='elastic_net', model_version=loaded.model_version_)
                pd.testing.assert_frame_equal(loaded.predict(transform_inputs(pre, prediction), context), pd.read_parquet(output / 'predictions.parquet'))
                checks.append(dict(task=target, information_set=info, save_load_predict=True,
                    predictions=len(prediction.keys), original_unit_scoring=True))
        from ..framework import paired_losses
        for target in ['classification', 'regression']:
            a = pd.read_parquet(Path(directory) / (target + 'M') / 'losses.parquet')
            b = pd.read_parquet(Path(directory) / (target + 'M_Z') / 'losses.parquet')
            paired_losses(a, b, task=target, schema=store.target_schema())
    summary = dict(purpose='SMOKE_ONLY', versions=identity, checks=checks, paired=True,
        research_evidence=False, retained_predictions=False, retained_weights=False)
    atomic_json(ROOT / smoke_config['summary'], summary)
    print('SMOKE_ONLY connectivity complete; no research scores retained')
