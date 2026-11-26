"""Random Forest results and retrospective diagnostics from committed fits."""
from pathlib import Path

import numpy as np
import pandas as pd

from ..common import CORE, KEY, ROOT
from ..model_contract import IDENTITY
from .artifacts import read_json
from .scoring import synchronized_bootstrap


def baseline_intervals(scores, config, stage):
    comparisons, labels = [], []
    for (market, task), part in scores.groupby(['market_id', 'task']):
        truth = ['future_state_id'] if task == 'classification' else CORE
        checked = KEY + ['fold_id', 'fit_cutoff', 'quality'] + IDENTITY + truth
        baselines = part[part['mode'].eq('baseline')]
        models = part[part.family.eq('random_forest')]
        for (mode, info), subset in models.groupby(['mode', 'information_set']):
            for family, baseline in baselines.groupby('family'):
                left = baseline.sort_values(KEY).reset_index(drop=True)
                matched = []
                for _, seed in subset.groupby('seed'):
                    right = seed.sort_values(KEY).reset_index(drop=True)
                    pd.testing.assert_frame_equal(left[checked], right[checked], check_exact=True)
                    matched.append(right.loss.to_numpy())
                model_loss = np.mean(matched, axis=0)
                name = '|'.join([market, task, mode, info, family])
                comparisons.append(left[['asof_date']].assign(comparison_id=name, loss_difference=left.loss - model_loss))
                labels.append(dict(comparison_id=name, market_id=market, task=task, mode=mode, information_set=info,
                    baseline=family, baseline_loss=float(left.loss.mean()), model_loss=float(model_loss.mean())))
    rules = config['statistics']
    values = pd.concat(comparisons, ignore_index=True)
    return pd.concat([
        synchronized_bootstrap(values, block_weeks=width, repetitions=rules['repetitions'],
            seed=rules['seed'], confidence=rules['confidence']).assign(stage=stage)
        for width in rules['block_weeks']], ignore_index=True).merge(pd.DataFrame(labels), on='comparison_id', validate='many_to_one')


def forest_tables(root, stage, assignments, scores, schema, config, increment):
    monthly, splits, targets, perturbation, probabilities = [], [], [], [], []
    for assignment in assignments:
        ident = assignment['identity']
        if ident['family'] != 'random_forest':
            continue
        meta = {key: ident[key] for key in ['market_id', 'fold_id', 'task', 'information_set', 'mode', 'seed']}
        directory = root / assignment['artifact']
        detail = read_json(directory / 'forest_diagnostics.json')
        groups = detail['split_counts_by_group']
        monthly.append(dict(meta, total_features=detail['total_input_features'],
            sampled_features=detail['actual_features_per_split'], trees=detail['n_trees'],
            total_splits=sum(groups.values()), macro_splits=detail['macro_split_count'],
            median_depth=detail['tree_depth_quantiles_0_25_50_75_100'][2],
            median_leaf_support=detail['leaf_distinct_rows_quantiles_0_25_50_75_100'][2]))
        for group, count in groups.items():
            splits.append(dict(meta, group=group, splits=count))
        for target, loss in detail.get('adapted_target_split_sse_reduction', {}).items():
            targets.append(dict(meta, target=target, adapted_split_sse_reduction=loss,
                weight=detail['adapted_target_weights'][target]))
        path = directory / 'perturbed_losses.parquet'
        if path.is_file():
            frame = pd.read_parquet(path)
            for name, value in meta.items():
                frame[name] = value
            perturbation.append(frame)
        path = directory / 'probability_evidence.parquet'
        if path.is_file():
            frame = pd.read_parquet(path)
            for cls in schema['class_ids']:
                p = frame['predicted_state_prob_' + str(cls)]
                probabilities.append(dict(meta, class_id=cls, predicted_rows=len(p), unique_probabilities=p.nunique(),
                    zero_probabilities=int(p.eq(0).sum()), one_probabilities=int(p.eq(1).sum()),
                    mean_probability=float(p.mean()) if len(p) else None,
                    median_leaf_support=float(frame.median_tree_leaf_distinct_rows.median()) if len(p) else None))
    tables = dict(forest_baseline_pairs=baseline_intervals(scores, config, stage),
        forest_monthly_diagnostics=pd.DataFrame(monthly), forest_group_splits=pd.DataFrame(splits),
        forest_target_split_reduction=pd.DataFrame(targets), forest_native_probability=pd.DataFrame(probabilities))
    if perturbation:
        shifts = pd.concat(perturbation, ignore_index=True)
        group = ['market_id', 'task', 'information_set', 'mode', 'group']
        metrics = [name.removesuffix('_real') for name in shifts if name.endswith('_real')]
        changes = shifts[group + ['asof_date']].copy()
        for metric in metrics:
            changes[metric] = shifts[metric + '_perturbed'] - shifts[metric + '_real']
        changes = changes.melt(id_vars=group + ['asof_date'], var_name='metric', value_name='loss_increase').dropna()
        group += ['metric']
        dated = changes.groupby(group + ['asof_date'], as_index=False).loss_increase.mean()
        tables['forest_group_perturbation'] = dated.groupby(group, as_index=False).loss_increase.agg(['mean', 'size']).reset_index(drop=True)
    historical = ROOT / 'reports/model_build/random_forest/prior_model_core.csv'
    if historical.is_file():
        prior = pd.read_csv(historical)
        common = increment[increment['mode'].eq('retuned_core') & increment.year.eq('all')
            & increment.block_weeks.eq(8) & increment.left.eq('M') & increment.right.eq('M+Z')
            & increment.metric.isin(['log_loss', 'five_dimension_squared'])].copy()
        common['study_stage'] = 'B' if stage == 'development' else 'C'
        keys = ['market_id', 'task', 'metric', 'study_stage']
        combined = common[keys + ['mean', 'lower', 'upper', 'n']].merge(prior, on=keys, how='inner')
        combined['same_score_count'] = combined.n.eq(combined.prior_n)
        combined['forest_minus_prior_gain'] = combined['mean'] - combined.prior_gain
        tables['forest_cross_model_reference'] = combined
    return tables


def forest_report(manifest, stage, increment, tables):
    primary = increment[increment.year.eq('all') & increment.block_weeks.eq(8)
        & increment.metric.isin(['log_loss', 'five_dimension_squared'])]
    lines = [
        '# 随机森林宏观信息复核', '',
        f'运行身份 `{manifest["run_id"]}`。阶段为' + ('历史测试 C。' if stage == 'test' else '开发 B。'), '',
        '原封版四市场、未来 20 交易日和目标定义。历史测试期曾在前两模型实验中查看。开发期选参、类别处理、种子和预警工作点在 C 开始前已锁定。', '',
        '## 三项配对增量', '',
        '分类采用 Log Loss，回归采用五维等权标准化平方损失。差值为左侧损失减右侧损失，正值有利于右侧。区间为同步 8 周区块 Bootstrap 的 95% 区间。', '',
        '| 市场 | 任务 | 参数 | 对照 | 周数 | 差值 | 95% 区间 |',
        '| --- | --- | --- | --- | ---: | ---: | ---: |',
    ]
    for row in primary.to_dict('records'):
        mode = '分别调参' if row['mode'] == 'retuned_core' else '固定 M 参数'
        task = '分类' if row['task'] == 'classification' else '回归'
        lines.append(f'| {row["market_id"]} | {task} | {mode} | {row["left"]} → {row["right"]} | {row["n"]} | '
            f'{row["mean"]:+.6f} | [{row["lower"]:+.6f}, {row["upper"]:+.6f}] |')
    lines += ['', '### 独立调参的区间方向', '']
    for (left, right, task), part in primary[primary['mode'].eq('retuned_core')].groupby(['left', 'right', 'task']):
        better = int(part.lower.gt(0).sum())
        worse = int(part.upper.lt(0).sum())
        label = '分类' if task == 'classification' else '回归'
        lines.append(f'- {left} → {right}，{label}。{better} 个市场的区间全正，{worse} 个全负，'
                     f'{len(part) - better - worse} 个包含零。')
    lines += ['', '## 概率、预警与风险维度', '',
        '分类表保存历史频率对照、Log Loss、Brier、逐类支持、OvR 排序、精确率和召回率。预警表使用开发阶段确定的 5%、10%、20%、30% 报警负担工作点。回归表保留七个目标原单位误差和五维结果。', '',
        '年度差值、各风险维度及七目标差值见 [配对明细](tables/macro_increment.csv)。'
        '训练均值、过去窗口持续值与历史频率的同步样本基准对比见 [基准对照](tables/forest_baseline_pairs.csv)。', '',
        '## 宏观组与历史模型', '',
        '分裂统计显示森林实际使用的宏观组及特征抽样绝对数量。各组循环扰动记录同周的损失变化，并在构造扰动输入时重算交互。它衡量已拟合模型对输入的依赖。各组删除后重新训练属于后续计划。', '']
    shifts = tables.get('forest_group_perturbation')
    if shifts is not None:
        lines.extend(['[宏观组扰动表](tables/forest_group_perturbation.csv)保留五维标准化平方损失、七项目标原单位绝对误差及分类损失变化。', ''])
        largest = shifts[shifts['mode'].eq('retuned_core') & shifts.group.ne('all_macro') & shifts.metric.eq('loss')]
        largest = largest.sort_values('mean', ascending=False).head(8)
        for row in largest.itertuples():
            lines.append(f'- {row.market_id} {row.task} {row.information_set} 的 {row.group} 扰动平均增加损失 {row.mean:+.6f}（{row.size} 周）。')
    historical = tables.get('forest_cross_model_reference')
    if historical is not None and len(historical):
        lines += ['', '历史原 Z 增量使用各自模型的正式报告。评分周数与版本限制在 [跨模型描述比较](tables/forest_cross_model_reference.csv) 保留。搜索空间、预处理和随机性随模型而异，跨模型差值的解释限于本次登记的比较。', '']
        for family, subset in historical.groupby('prior_family'):
            subset = subset[subset.same_score_count]
            lines.append(f'- 与 {family} 的同周数描述对照中，Random Forest 的原 Z 增量在 '
                f'{int(subset.forest_minus_prior_gain.gt(0).sum())}/{len(subset)} 个市场 × 任务组合更高。')
    lines += ['', '联合解释应考虑配对区间、基准表现、特征抽样维数以及低频发布的有效样本。模型容量、宏观表示与金融信息冗余的贡献需要额外设计辨识。', '']
    return lines
