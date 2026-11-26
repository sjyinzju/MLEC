"""Two fixed-parameter RBF-SVM sensitivities. Only run --execute trains."""
from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import pandas as pd

from ..common import ROOT, digest
from ..framework import DataStore, load_dataset, paired_losses
from ..interface_acceptance import assert_interface_accepted
from ..release import file_hash
from ..models.training import TrainingPartitions
from .artifacts import TaskJournal, atomic_json, atomic_parquet, exclusive_run, native_path, read_json
from .config import load_config
from .pipeline import Pipeline
from .portable import validate_source_receipt
from .runtime import MonthlyExecutor, environment, fold_lists, versions
from .scheduling import TaskRunner, TaskScheduler
from .scoring import classification_metrics, regression_metrics, synchronized_bootstrap


DESIGN = ROOT / 'config/experiments/rbf_followups_20261125.json'
MODEL_CONFIG = ROOT / 'config/experiments/rbf_macro_learning_20261125.yaml'
TEST_RECEIPT = ROOT / 'reports/market_state/model_io/test_results.json'
STAGES = ('development', 'test')
REFERENCE_MODES = ('fixed_full_params', 'retuned_core')
PARAMETER_MODE = 'fixed_followup'


def _reference(path, store):
    manifest = read_json(path / 'manifest.json')
    lock_path = path / 'selection.lock.json'
    lock = read_json(lock_path)
    lock_sha = file_hash(lock_path)
    if (manifest['state'] != 'EXPERIMENT_COMPLETE' or manifest['model'] != 'rbf_svm'
            or manifest['lock_hash'] != lock_sha or manifest['versions'] != lock['versions']
            or digest({k: v for k, v in lock.items() if k != 'content_hash'}) != lock['content_hash']
            or lock['versions']['data_version'] != store.data_version
            or lock['versions']['original_seal_hash'] != file_hash(store.root / 'release/seal.json')):
        raise ValueError('Previous 20d RBF-SVM selection lock or data identity differs')
    return lock, dict(run_id=manifest['run_id'], lock_sha256=lock_sha,
        scores_sha256={stage: file_hash(path / stage / 'metrics/selected_scores.parquet') for stage in STAGES})


def _parameters(lock, market, task, horizon):
    p = deepcopy(lock['parameters'][f'{market}|{task}|M+Z']['positive_weight_winner']['parameters'])
    if p['macro_weight'] <= 0:
        raise ValueError('The fixed reference must include a positive macro block')
    if horizon == 20:
        p.update(gamma_factor=p['gamma_factor'] * p['macro_weight'], macro_weight=1.)
    elif task == 'classification':
        p['calibrator'] = 'score_softmax'
    return p


class _FollowupRunner(TaskRunner):
    task = Pipeline.task
    checked_scores = Pipeline.checked_scores

    def __init__(self, root, config, store, resume):
        self.root, self.config, self.store = root, config, store
        self.identity = versions(config, store)
        self.artificial = False
        self.executor = MonthlyExecutor(config, store, self.identity)
        self.journal = TaskJournal(root, resume=resume, max_attempts=config['policy']['task_attempts'])
        self.scheduler = TaskScheduler(self)

    def stage(self, name, folds, lock, horizon, sets):
        plans = self.store.get('fold_membership')
        role = 'validation' if name == 'development' else 'test'
        last = plans[plans.role.eq(role)].groupby('market_id').fold_id.max()
        tasks = [self.task(stage=name, mode=PARAMETER_MODE, market=market, task=task, information=info,
                    fold=fold, parameters=_parameters(lock, market, task, horizon), seed=lock['seeds'][task][0])
            for market in self.config['markets'] for task in self.config['tasks'] for fold in folds for info in sets]
        if len({t['fit_id'] for t in tasks}) != len(tasks):
            raise ValueError('Duplicate follow-up fit identity')
        started = perf_counter()
        records = []
        for start in range(0, len(tasks), 64):
            batch = tasks[start:start + 64]
            jobs = [(t, t['identity']['fold_id'] == last[t['identity']['market_id']]) for t in batch]
            records.extend(self.scheduler.map(jobs))
            print(f'{horizon}d {name}: {len(records)}/{len(tasks)} monthly fits', flush=True)
        tagged = []
        for task, record in zip(tasks, records):
            identity = task['identity']
            scores = self.checked_scores(record)
            tagged.append(scores.assign(task=identity['task'], mode=identity['mode'], seed=identity['seed'],
                fit_id=record['fit_id']))
        scores = pd.concat(tagged, ignore_index=True)
        atomic_parquet(self.root / name / 'scores.parquet', scores)
        return scores, dict(monthly_fits=len(records), elapsed_seconds=perf_counter() - started,
            estimator_fit_calls=sum(r['estimator_fit_calls'] for r in records),
            calibration_fit_calls=sum(r['calibration_fit_calls'] for r in records),
            prediction_rows=sum(r['predictions'] for r in records), mature_rows=len(scores),
            last_scored_package_folds=last.to_dict())


def _fixed_calibration_evidence(store, config, folds):
    rows = []
    for market in config['markets']:
        for fold in (folds[0], '2022-12'):
            train = load_dataset(market_id=market, task='classification', fold_id=fold, role='train',
                information_set='M', store=store)
            service = TrainingPartitions(train)
            plan = service.plan(config['calibration'])
            summary = service.support_summary(plan)
            counts = train.y.future_state_id.value_counts().sort_index()
            rows.append(dict(market_id=market, fold_id=fold, outer_training_rows=len(train.keys),
                outer_class_counts={str(c): int(n) for c, n in counts.items()},
                original_time_oof=summary, accepted_blocks=sum(b['status'] == 'ACCEPTED' for b in plan)))
    return rows


def _run_horizon(root, store, config, lock, reference, horizon, study, resume):
    name = f'{horizon}d'
    design = study['experiments'][name]
    sets = design['information_sets']
    dev, test = fold_lists(store)
    config = deepcopy(config)
    with exclusive_run(root):
        runner = _FollowupRunner(root, config, store, resume)
        path = root / 'plan.json'
        plan = dict(study=study['study'], scope=design, versions=runner.identity, reference=reference,
            development_folds=dev, test_folds=test, parameters={f'{m}|{t}': _parameters(lock, m, t, horizon)
                for m in config['markets'] for t in config['tasks']})
        if path.exists():
            if not resume or read_json(path) != plan:
                raise ValueError('Existing follow-up run requires --resume with identical inputs and code')
        else:
            atomic_json(path, plan)
        scores, stats = {}, {}
        status = 'FAILED'
        try:
            if horizon == 60:
                atomic_json(root / 'calibration_support.json', _fixed_calibration_evidence(store, config, dev))
            for stage, folds in zip(STAGES, (dev, test)):
                scores[stage], stats[stage] = runner.stage(stage, folds, lock, horizon, sets)
            status = 'COMPLETE'
        finally:
            runner.scheduler.close()
            atomic_json(root / 'execution.json', dict(status=status, stages=stats, plan_sha256=file_hash(path)))
    return scores, stats


def _metrics(scores, schema, *, stage, horizon, mode):
    rows = []
    for (market, task, info), part in scores.groupby(['market_id', 'task', 'information_set']):
        metrics = classification_metrics(part, schema)[0] if task == 'classification' else regression_metrics(part)
        if task == 'classification':
            support = part.future_state_id.value_counts()
            metrics.update({f'true_class_{c}': int(support.get(c, 0)) for c in schema['class_ids']})
        rows.append(dict(stage=stage, horizon=horizon, mode=mode, market_id=market, task=task,
            information_set=info, first_week=part.asof_date.min(), last_week=part.asof_date.max(), **metrics))
    return rows


def _compare(left, right, schema, name):
    rows = []
    for (market, task), part in left.groupby(['market_id', 'task']):
        other = right[right.market_id.eq(market) & right.task.eq(task)]
        paired = paired_losses(part, other, task=task, schema=schema)
        rows.append(paired[['asof_date', 'loss_difference']].assign(
            comparison_id=f'{name}|{market}|{task}', loss_left=paired.loss_M, loss_right=paired.loss_MZ))
    return pd.concat(rows, ignore_index=True)


def _score(root, by_horizon, reference_path, reference, stores, design, config):
    metrics, effects = [], []
    for stage in STAGES:
        within_60 = by_horizon[60][stage]
        schema = stores[60].target_schema()
        metrics.extend(_metrics(within_60, schema, stage=stage, horizon=60, mode=PARAMETER_MODE))
        mzk = within_60.information_set.eq('M+Z')
        comparisons_60 = _compare(within_60[~mzk], within_60[mzk], schema, 'M_vs_M+Z')
        z_scores = by_horizon[20][stage]
        if not z_scores.information_set.eq('Z').all():
            raise ValueError('Expected only Z scores in the macro-only run')
        schema = stores[20].target_schema()
        metrics.extend(_metrics(z_scores, schema, stage=stage, horizon=20, mode=PARAMETER_MODE))
        path = reference_path / stage / 'metrics/selected_scores.parquet'
        if file_hash(path) != reference['scores_sha256'][stage]:
            raise ValueError('The reference scores changed while fitting')
        prior = pd.read_parquet(path)
        prior = prior[prior.family.eq('rbf_svm') & prior.information_set.isin(['M', 'M+Z'])]
        comparisons_20 = []
        for mode in REFERENCE_MODES:
            subset = prior[prior['mode'].eq(mode)]
            metrics.extend(_metrics(subset, schema, stage=stage, horizon=20, mode=mode))
            for info in ('M', 'M+Z'):
                selected = subset[subset.information_set.eq(info)]
                comparisons_20.append(_compare(selected, z_scores, schema, f'{mode}:{info}_vs_Z'))
            comparisons_20.append(_compare(subset[subset.information_set.eq('M')],
                subset[subset.information_set.eq('M+Z')], schema, f'{mode}:M_vs_M+Z'))
        for horizon, pairs in ((20, pd.concat(comparisons_20, ignore_index=True)), (60, comparisons_60)):
            statistics = config['statistics']
            blocks = design['experiments'][f'{horizon}d']['bootstrap_weeks']
            means = pairs.groupby('comparison_id')[['loss_left', 'loss_right']].mean().reset_index()
            for weeks in blocks:
                ci = synchronized_bootstrap(pairs, block_weeks=weeks, repetitions=statistics['repetitions'],
                    seed=statistics['seed'], confidence=statistics['confidence'])
                effects.append(ci.merge(means, on='comparison_id', validate='one_to_one').assign(
                    stage=stage, horizon=horizon, main_block=weeks == blocks[0]))
    metrics = pd.DataFrame(metrics)
    effects = pd.concat(effects, ignore_index=True)
    effects[['comparison', 'market_id', 'task']] = effects.comparison_id.str.split('|', regex=False, expand=True)
    metrics.to_csv(root / 'metrics.csv', index=False, encoding='utf-8-sig')
    effects.to_csv(root / 'paired_intervals.csv', index=False, encoding='utf-8-sig')
    return metrics, effects


def _write_report(path, metrics, effects, stats):
    market_names = {'000985.SH': '全 A', '000300.SH': '沪深 300', '000905.SH': '中证 500', '000852.SH': '中证 1000'}
    lines = ['# RBF-SVM 两项扩展实验', '',
        '同一封版快照、四个市场、三状态分类和七项回归。形成月初模型时只使用已经成熟的标签。', '',
        '## 60 个交易日', '',
        '历史特征数值沿用原 20 日数据。未来标签从锚点后第 1 个交易日测到第 60 个交易日。',
        '状态词典用 2019 年底前成熟的四市场样本重拟合。60 日早期下跌状态难以形成合格的跨时间校准样本。',
        '两组分类使用相同的 RBF-SVC 和固定 softmax 分数映射，回归使用同一组七个 RBF-SVR 参数。', '',
        '## 20 个交易日，仅 Z', '',
        'Z 使用原主视图的宏观列，保留原锁定的宏观核指数系数和同一套时间校准规则。',
        '保留严格对齐的原 20 日 M、M+Z 对照，主表引用上一轮分别调参的结果。', '',
        '## 样本外测试结果', '',
        '分类为对数损失，回归为固定初始尺度的五维标准化均方误差。两者都是越小越好。',
        '配对差值为左侧减右侧，正数表示右侧损失更低。区间使用同步周移动区块 bootstrap。', '',
        '| 实验 | 市场 | 任务 | 周数 | 左侧损失 | 右侧损失 | 差值 | 95% 区间 |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    main = effects[effects.stage.eq('test') & effects.main_block & effects.comparison.isin(
        ['M_vs_M+Z', 'retuned_core:M_vs_Z', 'retuned_core:M+Z_vs_Z'])]
    for r in main.sort_values(['horizon', 'comparison', 'market_id', 'task'], ascending=[False, True, True, True]).itertuples():
        comparison = r.comparison.removeprefix('retuned_core:').replace('_vs_', ' → ')
        task = '分类' if r.task == 'classification' else '回归'
        lines.append(f'| {r.horizon} 日 {comparison} | {market_names[r.market_id]} | {task} | {r.n} | '
            f'{r.loss_left:.4f} | {r.loss_right:.4f} | {r.mean:+.4f} | [{r.lower:+.4f}, {r.upper:+.4f}] |')
    lines += ['', '60 日和 20 日的标签与回归标准化尺度不同。表内差值在同一预测期的相同周上计算。',
        '全部市场、开发期、固定参数对照、区块长度敏感性和七个原单位回归指标见同目录 CSV。', '']
    for horizon, stages in stats.items():
        count = sum(x['monthly_fits'] for x in stages.values())
        test = metrics[metrics.stage.eq('test') & metrics.horizon.eq(horizon) & metrics['mode'].eq(PARAMETER_MODE)]
        lines.append(f'- {horizon} 日完成 {count} 个市场×任务×信息集×月份的实际拟合。'
            f'测试评分周截至 {test.last_week.max():%Y-%m-%d}。')
    path.write_text('\n'.join(lines) + '\n', encoding='utf8')


def execute(args):
    design = read_json(DESIGN)
    root = native_path(args.output)
    reference_path = Path(args.previous_run).resolve()
    stores = {20: DataStore(args.data20), 60: DataStore(args.data60)}
    if any(root == native_path(p) or root.is_relative_to(native_path(p)) for p in
            [reference_path, *(s.root for s in stores.values())]):
        raise ValueError('Output must be separate from the input data and reference run')
    lock, reference = _reference(reference_path, stores[20])
    seal60 = read_json(stores[60].root / 'release/seal.json')
    if (seal60.get('horizon') != 60 or seal60.get('historical_input_design') or seal60['parent_data_version'] != stores[20].data_version
            or seal60['parent_seal_sha256'] != lock['versions']['original_seal_hash']):
        raise ValueError('The derived 60d release is from another parent')
    test_receipt = read_json(TEST_RECEIPT)
    validate_source_receipt(test_receipt)
    for horizon, receipt in ((20, args.interface20), (60, args.interface60)):
        assert_interface_accepted(data_root=stores[horizon].root, receipt_dir=receipt,
            required_information_sets=design['experiments'][f'{horizon}d']['information_sets'])
    config = load_config(MODEL_CONFIG)
    config['purpose'] = 'EXPLORATORY'
    config['warning']['enabled'] = False
    config['rbf_design']['perturbation'] = None
    config['resources']['cpu_workers'] = args.workers
    env = environment()
    with exclusive_run(root):
        atomic_json(root / 'run_inputs.json', dict(environment=env, study=design, design_sha256=file_hash(DESIGN),
            reference=reference, tests=dict(passed=test_receipt['passed'], sha256=file_hash(TEST_RECEIPT)),
            interface_sha256={str(h): file_hash(p / 'acceptance.json') for h, p in
                ((20, args.interface20), (60, args.interface60))}))
        scores, stats = {}, {}
        for horizon in (60, 20):
            scores[horizon], stats[horizon] = _run_horizon(root / f'h{horizon}', stores[horizon], config,
                lock, reference, horizon, design, args.resume)
        metrics, effects = _score(root, scores, reference_path, reference, stores, design, config)
        _write_report(root / 'report.md', metrics, effects, stats)
        atomic_json(root / 'execution.json', dict(status='COMPLETE', monthly_execution=stats,
            outputs={name: file_hash(root / name) for name in ['report.md', 'metrics.csv', 'paired_intervals.csv']},
            plan_sha256={str(h): file_hash(root / f'h{h}' / 'plan.json') for h in stores},
            evidence_sha256={str(h): file_hash(root / f'h{h}' / 'execution.json') for h in stores}))
    print('RBF-SVM FOLLOW-UPS COMPLETE', root, flush=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--data20', type=Path)
    parser.add_argument('--data60', type=Path, required=True)
    parser.add_argument('--interface20', type=Path, required=True)
    parser.add_argument('--interface60', type=Path, required=True)
    parser.add_argument('--previous-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=0)
    args = parser.parse_args()
    if args.workers < 0:
        parser.error('--workers must be nonnegative')
    if args.execute:
        execute(args)
    else:
        print('Follow-up design only; fits=0 without --execute')


if __name__ == '__main__':
    main()
