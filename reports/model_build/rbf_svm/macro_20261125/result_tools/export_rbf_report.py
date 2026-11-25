"""Summarize an already evaluated RBF run. This helper fits no models."""
from argparse import ArgumentParser
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist

from scripts.market_state.common import KEY
from scripts.market_state.framework import DataStore, load_dataset
from scripts.market_state.model_contract import transform_inputs
from scripts.market_state.models.rbf_svm import RBFSVMAdapter, relative_gamma

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def exact_selected_geometry(root, stage, config):
    store = DataStore(config['data_root'])
    records = []
    chosen = read(root / stage / 'selection/assignments.json')
    last = '2022-12' if stage == 'development' else '2026-10'
    for a in chosen:
        i = a['identity']
        if i['mode'] != 'retuned_core' or i['fold_id'] != last:
            continue
        path = root / a['artifact']
        package = path/'model_package'
        model = RBFSVMAdapter.load(package)
        args = dict(market_id=i['market_id'], information_set=i['information_set'],
            task=i['task'], fold_id=last, quality=config['quality'], store=store)
        pre = model.preprocessor
        train = load_dataset(**args, role='train')
        validation = load_dataset(**args, role='validation' if stage=='development' else 'test')
        X, Xv = transform_inputs(pre, train), transform_inputs(pre, validation)
        raw_a, raw_b = X.to_numpy(), Xv.to_numpy()
        mask = np.array([c.removeprefix('missing__').startswith('macro__') for c in X])
        scales = np.ones(X.shape[1])
        market_rms = float(np.sqrt(np.mean(raw_a[:, ~mask] ** 2)))
        macro_rms = float(np.sqrt(np.mean(raw_a[:, mask] ** 2))) if mask.any() else None
        scales[~mask] = market_rms
        if macro_rms:
            scales[mask] = macro_rms
        eta = i['parameters']['gamma_factor']
        comparator_gamma = relative_gamma(raw_a / scales, eta)
        exact = model.geometry_.compare(X, Xv, eta, relative_gamma(X, eta), max_train_rows=len(X))
        for name, rows, raw_left in [('train_train', X, raw_a), ('validation_train', Xv, raw_b)]:
            if not len(rows):
                continue
            new = np.exp(-eta * cdist(model.geometry_.transform(rows), model.geometry_.transform(X), 'sqeuclidean'))
            old = np.exp(-comparator_gamma * cdist(raw_left / scales, raw_a / scales, 'sqeuclidean'))
            if name == 'train_train':
                off = ~np.eye(len(X), dtype=bool)
                new, old = new[off], old[off]
            records.append(dict(stage=stage, market_id=i['market_id'], task=i['task'], information_set=i['information_set'],
                fold=last, artifact=a['artifact'], model_version=model.model_version_, n_train=len(X), n_scored=len(Xv), pairing=name,
                parameters=i['parameters'], per_element_rms_proxy=dict(market=market_rms, macro=macro_rms,
                    relative=macro_rms / market_rms if macro_rms else None, gamma=comparator_gamma,
                    kernel_rms_change=float(np.sqrt(np.mean((new-old)**2)))),
                exact=exact['train_train' if name == 'train_train' else 'prediction_train']))
    return records

def candidate_contrasts(root):
    rows = []
    search = read(root / 'development/selection/search.json')
    for v in search.values():
        if v['information_set'] not in ['M', 'M+Z']:
            continue
        profiles = [p for p in v['full_review'] if p['valid']]
        kinds = ['class_weight', 'calibrator'] if v['task'] == 'classification' else ['C', 'epsilon']
        if v['information_set'] == 'M+Z':
            kinds += ['representation', 'macro_weight']
        for kind in kinds:
            for l, left in enumerate(profiles):
                a = left['parameters']
                for right in profiles[l+1:]:
                    b = right['parameters']
                    if a[kind] == b[kind] or any(a[k] != b[k] for k in a if k != kind):
                        continue
                    rows.append(dict(market_id=v['market_id'], task=v['task'], information_set=v['information_set'],
                        field=kind, left_value=a[kind], right_value=b[kind], loss_left=left['score'], loss_right=right['score'],
                        loss_left_minus_right=left['score']-right['score'], left_id=left['candidate_id'], right_id=right['candidate_id'],
                        weeks=left['n'], class_support=left.get('class_support'), event_runs=left.get('event_runs')))
        if v['information_set'] == 'M+Z':
            core = search[v['market_id'] + '|' + v['task'] + '|M']['full_review']
            fixed = lambda p: {k: value for k, value in p.items() if k not in ['macro_weight', 'representation']}
            for right in profiles:
                left = next(p for p in core if fixed(p['parameters']) == fixed(right['parameters']))
                if not left['valid']:
                    continue
                assert left['n'] == right['n'] and left.get('class_support') == right.get('class_support')
                rows.append(dict(market_id=v['market_id'], task=v['task'], information_set='M|M+Z',
                    field='paired_macro', left_value=0, right_value=right['parameters']['macro_weight'],
                    representation=right['parameters']['representation'], loss_left=left['score'], loss_right=right['score'],
                    loss_left_minus_right=left['score'] - right['score'], left_id=left['candidate_id'],
                    right_id=right['candidate_id'], weeks=left['n'], class_support=left.get('class_support'),
                    event_runs=left.get('event_runs'), target_losses_left=left.get('target_scores'),
                    target_losses_right=right.get('target_scores')))
    return rows

def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = read(root/'manifest.json')
    if not manifest['development_complete'] or not manifest['test_complete']:
        raise SystemExit('Both formal stages must complete before final export')
    lock = root/'selection.lock.json'
    if sha(lock) != manifest['lock_hash']:
        raise SystemExit('Lock tamper or incomplete run')
    destination = root/'delivery'
    destination.mkdir(exist_ok=True)
    config = read(root/'config.resolved.yaml')
    release = candidate_contrasts(root)
    (destination/'candidate_matched_contrasts.json').write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding='utf8')
    geometry = exact_selected_geometry(root, 'development', config) + exact_selected_geometry(root, 'test', config)
    (destination/'selected_exact_kernel.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf8')
    products={}
    for phase, table_path in [('development',root/'development/tables'), ('test',root/'tables')]:
        inc=pd.read_csv(table_path/'macro_increment.csv')
        selection=inc[(inc['mode']=='retuned_core') & inc.metric.isin(['log_loss','five_dimension_squared']) & (inc.block_weeks==8)]
        products[phase]=selection.to_dict('records')
    frame = pd.DataFrame(products['test'])
    print(frame[frame.year.eq('all')][['market_id','task','mean','lower','upper','n']].to_string(index=False))

if __name__=='__main__':
    main()
