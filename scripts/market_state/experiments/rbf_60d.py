"""Independently select and evaluate RBF-SVM on the rebuilt 60d data release."""
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter

import pandas as pd

from ..common import ROOT, digest
from ..framework import DataStore
from ..horizons import HISTORY_DESIGN, HORIZON, SETS
from ..interface_acceptance import assert_interface_accepted
from ..models.rbf_geometry import GEOMETRY_VERSION
from ..models.specifications import complexity, validate_parameters
from ..release import file_hash
from .artifacts import atomic_json, atomic_parquet, exclusive_run, native_path, read_json
from .config import load_config
from .pipeline import Pipeline, group_id
from .portable import validate_source_receipt
from .rbf_followups import _FollowupRunner, _compare, _fixed_calibration_evidence, _metrics
from .runtime import environment, fold_lists
from .scoring import synchronized_bootstrap


DESIGN = ROOT / 'config/experiments/rbf_60d_retuned_20261126.json'
DOCUMENT = 'docs/rbf_60d_retuned_20261126.md'
TEST_RECEIPT = ROOT / 'reports/market_state/model_io/test_results.json'
MODES = ('retuned_core', 'fixed_positive_macro')


def candidates(design, task, information):
    result = []
    for layout in design['macro_layouts']:
        if information == 'M' and layout['macro_weight'] > 0:
            continue
        for gamma in design['gamma_factors']:
            for profile in design['profiles'][task]:
                parameters = dict(layout, gamma_factor=gamma, geometry_version=GEOMETRY_VERSION,
                    **profile, **design['solver'])
                validate_parameters('rbf_svm', task, parameters)
                result.append(dict(candidate_id=digest(parameters)[:16], parameters=parameters,
                    complexity_order=complexity('rbf_svm', task, parameters)))
    if len({r['candidate_id'] for r in result}) != len(result) or not result:
        raise ValueError('Duplicate or empty 60d search grid')
    return result


def _development_scope(store, schedule):
    validation = store.get('fold_membership').query('role == "validation"')
    groups = validation.groupby('fold_id').market_id.nunique()
    if groups.empty or not groups.eq(len(store.spec['by_market'])).all():
        raise ValueError('Development folds need synchronized mature cohorts')
    folds = [f for f in schedule if f in groups]
    if len(folds) != len(groups):
        raise ValueError('Mature 60d validation fold is outside development')
    return folds, validation.groupby('market_id').size().to_dict()


def _bound_document(path, payload):
    atomic_json(path, dict(payload, content_hash=digest(payload)))


def _read_bound(path):
    document = read_json(path)
    expected = document.pop('content_hash')
    if expected != digest(document):
        raise ValueError('Study evidence content hash changed: ' + path.name)
    return document


class _RetunedRunner(_FollowupRunner):
    weighted = True
    candidate_score = Pipeline.candidate_score
    weighted_winner = Pipeline.weighted_winner
    rank = staticmethod(Pipeline.rank)

    def search(self, plan):
        design, folds = plan['design'], plan['search_folds']
        all_groups = {}
        for market in self.config['markets']:
            for task in self.config['tasks']:
                for information in SETS:
                    key = group_id(market, task, information)
                    grid = candidates(design, task, information)
                    group_path = self.root / 'development/search' / (key.replace('|', '_') + '.json')
                    jobs = [self.task(stage='development', mode='search_60d', market=market, task=task,
                        information=information, fold=fold, parameters=c['parameters'], seed=design['seed'])
                        for fold in folds for c in grid]
                    identity = dict(group=key, expected_folds=folds, task_ids=[t['task_id'] for t in jobs],
                        plan_sha256=file_hash(self.root / 'plan.json'))
                    if group_path.exists():
                        evidence = _read_bound(group_path)
                        if evidence['identity'] != identity:
                            raise ValueError('Cached development group identity changed: ' + key)
                        rows = evidence['candidates']
                    else:
                        print('60d search', key, len(grid), 'candidates x', len(folds), 'months', flush=True)
                        results = self.scheduler.map([(job, False) for job in jobs], allow_fit_failure=True)
                        rows = [self.candidate_score(results[i::len(grid)], task, candidate, folds)
                            for i, candidate in enumerate(grid)]
                        _bound_document(group_path, dict(identity=identity, candidates=rows))
                    if (len(rows) != len(grid) or any((r['candidate_id'], r['parameters']) != (c['candidate_id'], c['parameters'])
                            for r, c in zip(rows, grid))
                            or any(r['n'] != plan['development_weeks'][market] for r in rows if r['valid'])):
                        raise ValueError('Incomplete candidate selection evidence: ' + key)
                    winner = self.weighted_winner(rows, task)
                    positive = self.weighted_winner(rows, task, positive_only=True) if information == 'M+Z' else None
                    all_groups[key] = dict(winner=winner, positive=positive, evidence=group_path.relative_to(self.root).as_posix(),
                        sha256=file_hash(group_path), candidates=len(rows), valid=sum(r['valid'] for r in rows))
                    print('60d selection', len(all_groups), '/ 16', key, 'loss', round(winner['score'], 6), flush=True)
        return all_groups

    def evaluate(self, stage, folds, groups, seed):
        role = 'validation' if stage == 'development' else 'test'
        membership = self.store.get('fold_membership')
        scored = membership[membership.role.eq(role)]
        last = scored.groupby('market_id').fold_id.max().to_dict()
        tasks = []
        for market in self.config['markets']:
            for task in self.config['tasks']:
                positive = groups[group_id(market, task, 'M+Z')]['positive']['parameters']
                for fold in folds:
                    for mode in MODES:
                        for information in SETS:
                            params = groups[group_id(market, task, information)]['winner']['parameters'] if mode == 'retuned_core' else positive
                            job = self.task(stage=stage, mode=mode, market=market, task=task,
                                information=information, fold=fold, parameters=params, seed=seed)
                            tasks.append((job, stage == 'test' and fold == last[market]))
        started = perf_counter()
        records = []
        for begin in range(0, len(tasks), 128):
            records.extend(self.scheduler.map(tasks[begin:begin + 128]))
            print(f'60d {stage} selected {len(records)}/{len(tasks)}', flush=True)
        frames = []
        for (job, _), record in zip(tasks, records):
            key = job['identity']
            frames.append(self.checked_scores(record).assign(task=key['task'], mode=key['mode'], fit_id=job['fit_id']))
        scores = pd.concat(frames, ignore_index=True)
        expected = scored.groupby('market_id').size().to_dict()
        for (market, _, _, _), part in scores.groupby(['market_id', 'task', 'mode', 'information_set']):
            if len(part) != expected[market] or part.asof_date.duplicated().any():
                raise ValueError('A selected prediction does not cover its complete scoring cohort')
        atomic_parquet(self.root / stage / 'scores.parquet', scores)
        return scores, dict(logical_tasks=len(tasks), physical_fits=len({r['fit_id'] for r in records}),
            maturity_rows=len(scores), elapsed_seconds=perf_counter() - started, last_scored_fold=last)


def _results(root, by_stage, store, design, lock):
    metrics, intervals = [], []
    schema = store.target_schema()
    rules = design['bootstrap']
    for stage, scores in by_stage.items():
        parts = []
        for mode, group in scores.groupby('mode'):
            metrics.extend(_metrics(group, schema, stage=stage, horizon=HORIZON, mode=mode))
            choose = group.information_set.eq('M+Z')
            parts.append(_compare(group[~choose], group[choose], schema, mode))
        pairs = pd.concat(parts, ignore_index=True)
        means = pairs.groupby('comparison_id')[['loss_left', 'loss_right']].mean().reset_index()
        for block in rules['block_weeks']:
            ci = synchronized_bootstrap(pairs, block_weeks=block, repetitions=rules['repetitions'],
                seed=rules['seed'], confidence=rules['confidence'])
            intervals.append(ci.merge(means, on='comparison_id', validate='one_to_one').assign(stage=stage,
                main_block=block == rules['block_weeks'][0]))
    metrics, intervals = pd.DataFrame(metrics), pd.concat(intervals, ignore_index=True)
    intervals[['mode', 'market_id', 'task']] = intervals.comparison_id.str.split('|', regex=False, expand=True)
    metrics.to_csv(root / 'metrics.csv', index=False, encoding='utf-8-sig')
    intervals.to_csv(root / 'paired_intervals.csv', index=False, encoding='utf-8-sig')
    market_names = dict(zip(store.spec['by_market'], ['全 A', '沪深 300', '中证 500', '中证 1000']))
    out = ['# 60 个交易日 RBF-SVM 独立重训', '',
        '市场输入从过去 15、60、180 个交易日重算，当前和跨市场状态使用过去 60 日。宏观输入按发布时点重建，加入 60 日发布值变化。',
        '三状态字典在 2019 年底前成熟的 60 日标签上独立选择和拟合。分类核、正则化、类别权重和 softmax 温度均由 60 日开发段选择。',
        '每个市场和任务分别选择 M 和 M+Z。另用开发段择优的正宏观权重参数固定求解器，对比仅移入宏观块的效果。', '',
        '## 测试段', '',
        '分类使用对数损失，回归使用五维标准化均方误差。差值为 M 减 M+Z，正值表示宏观组损失更低。', '',
        '| 对照 | 市场 | 任务 | 周数 | M | M+Z | 差值与 95% 区间 | M+Z 宏观权重 |',
        '|---|---|---|---:|---:|---:|---|---:|']
    selected = intervals[intervals.stage.eq('test') & intervals.main_block]
    for row in selected.sort_values(['mode', 'market_id', 'task']).itertuples():
        group = lock['groups'][group_id(row.market_id, row.task, 'M+Z')]
        weight = group['winner' if row.mode == 'retuned_core' else 'positive']['parameters']['macro_weight']
        mode = '分别选参' if row.mode == 'retuned_core' else '同参加入宏观'
        task = '分类' if row.task == 'classification' else '回归'
        out.append(f'| {mode} | {market_names[row.market_id]} | {task} | {row.n} | {row.loss_left:.4f} | {row.loss_right:.4f} | '
            f'{row.mean:+.4f} [{row.lower:+.4f}, {row.upper:+.4f}] | {weight:g} |')
    out += ['', '主区间由 2,000 次同步 16 周移动区块 bootstrap 得到。12 周和 20 周敏感性见配对明细。',
        '历史测试范围曾用于既有敏感性实验。本轮参数在读测试评分前由新的 60 日开发段锁定。', '']
    (root / 'report.md').write_text('\n'.join(out), encoding='utf8')


def execute(args):
    design = read_json(DESIGN)
    store = DataStore(args.data_root)
    root = native_path(args.output)
    if root.is_relative_to(native_path(store.root)):
        raise ValueError('Keep experiment output outside the sealed data release')
    if (store.spec.get('horizon') != HORIZON or store.spec.get('historical_input_design') != HISTORY_DESIGN
            or store.spec['historical_feature_dictionary_version'] != store.spec['label_version']):
        raise ValueError('The independent run requires the rebuilt 60d historical inputs')
    assert_interface_accepted(data_root=store.root, receipt_dir=args.interface, required_information_sets=SETS)
    tests = read_json(TEST_RECEIPT)
    validate_source_receipt(tests)
    config = load_config(ROOT / 'config/experiments/rbf_svm.yaml')
    config.update(purpose=design['purpose'], search=design, rbf_design=dict(version=GEOMETRY_VERSION,
        study=design['study'], perturbation=None, document=DOCUMENT))
    config['resources'].update(cpu_workers=args.workers, max_run_gb=12)
    config['warning']['enabled'] = False
    development, test = fold_lists(store)
    fit_folds, weeks = _development_scope(store, development)
    with exclusive_run(root):
        runner = _RetunedRunner(root, config, store, args.resume)
        path = root / 'plan.json'
        plan = dict(design=design, design_sha256=file_hash(DESIGN), versions=runner.identity, environment=environment(),
            development_folds=development, search_folds=fit_folds, test_folds=test, development_weeks=weeks,
            pytest_passed=tests['passed'], pytest_sha256=file_hash(TEST_RECEIPT),
            interface_sha256=file_hash(args.interface / 'acceptance.json'))
        if path.exists():
            if not args.resume or read_json(path) != plan:
                raise ValueError('Resume requires the original 60d design, versions and data')
        else:
            atomic_json(path, plan)
        atomic_json(root / 'calibration_support.json', _fixed_calibration_evidence(store, config, development))
        lock_path = root / 'selection.lock.json'
        existing_lock = _read_bound(lock_path) if lock_path.exists() else None
        status, stages = 'FAILED', {}
        try:
            groups = runner.search(plan)
            lock = dict(stage='development', plan_sha256=file_hash(path), versions=runner.identity, groups=groups,
                search_folds=fit_folds, test_folds=test, read_test_metrics_for_selection=False)
            if existing_lock is not None and any(existing_lock.get(k) != v for k, v in lock.items()):
                raise ValueError('Development lock changed on resume')
            scores = {}
            scores['development'], stages['development'] = runner.evaluate('development', development, groups, design['seed'])
            lock['development_scores_sha256'] = file_hash(root / 'development/scores.parquet')
            if existing_lock is None:
                _bound_document(lock_path, lock)
            elif existing_lock != lock:
                raise ValueError('Development score evidence changed on resume')
            if _read_bound(lock_path) != lock:
                raise ValueError('Development lock read-back failed')
            print('60d B lock verified', file_hash(lock_path), flush=True)
            scores['test'], stages['test'] = runner.evaluate('test', test, lock['groups'], design['seed'])
            _results(root, scores, store, design, lock)
            status = 'COMPLETE'
        finally:
            runner.scheduler.close()
            fits = {r['fit_id']: r for r in runner.journal.records.values() if r['status'] == 'SUCCEEDED'}
            outputs = ['report.md', 'metrics.csv', 'paired_intervals.csv'] if status == 'COMPLETE' else []
            atomic_json(root / 'execution.json', dict(status=status, stages=stages, successful_physical_fits=len(fits),
                successful_estimator_calls=sum(r['estimator_fit_calls'] for r in fits.values()),
                outputs={name: file_hash(root / name) for name in outputs},
                selection_lock_sha256=file_hash(lock_path) if lock_path.exists() else None))
    print('60d RBF-SVM RETUNE COMPLETE', root, flush=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--interface', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=0)
    args = parser.parse_args()
    if args.workers < 0:
        parser.error('--workers must be nonnegative')
    if args.execute:
        execute(args)
    else:
        print('60d design only; fits=0 without --execute')


if __name__ == '__main__':
    main()
