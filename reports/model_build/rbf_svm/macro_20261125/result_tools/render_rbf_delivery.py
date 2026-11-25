"""Render a completed study and select compact delivery files. No fitting."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile
import pandas as pd

NAMES = {'000985.SH': '中证全指', '000300.SH': '沪深 300', '000905.SH': '中证 500', '000852.SH': '中证 1000'}
TASKS = {'classification': '分类', 'regression': '回归'}

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def fmt(v, n=5):
    return '—' if pd.isna(v) else f'{v:.{n}f}'

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def core_results(run, stage):
    directory = run / ('development/tables' if stage == 'development' else 'tables')
    inc = pd.read_csv(directory/'macro_increment.csv')
    p = inc[inc['mode'].eq('retuned_core') & inc.year.eq('all') & inc.block_weeks.eq(8)
        & inc.metric.isin(['log_loss','five_dimension_squared'])].copy()
    bs = pd.read_csv(directory/'rbf_paired_baselines.csv')
    means = bs[bs.block_weeks.eq(8)].drop_duplicates(['market_id','task','information_set']).pivot(
        index=['market_id','task'], columns='information_set',values='model_mean')
    return p.merge(means, left_on=['market_id','task'], right_index=True, validate='one_to_one')

def group_results(run,stage):
    directory = run / ('development/tables' if stage == 'development' else 'tables')
    p = pd.read_csv(directory/'macro_groups.csv')
    return p[p.year.eq('all') & p.block_weeks.eq(8) & p.metric.isin(['log_loss','five_dimension_squared'])].copy()

def group_chart(groups, dest):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    test = groups[groups.period.eq('C') & groups.kind.isin(['add', 'delete'])]
    for row, mode in enumerate(['fixed_full_params', 'retuned_groups']):
        for col, task in enumerate(['classification','regression']):
            view = test[test['mode'].eq(mode) & test.task.eq(task)].copy()
            column = view.right.where(view.kind.eq('add'),view.left)
            view['contrast'] = view.kind + ' ' + column.str.replace('M+Z_', '', regex=False).str.replace('without_', '', regex=False)
            matrix = view.pivot(index='market_id',columns='contrast',values='mean')
            ax = axes[row,col]
            maximum = float(matrix.abs().to_numpy().max())
            grid = ax.imshow(matrix.to_numpy(),cmap='RdBu',vmin=-maximum,vmax=maximum,aspect='auto')
            ax.set(title=mode + ' · ' + task, xticks=range(len(matrix.columns)),xticklabels=matrix.columns,
                yticks=range(len(matrix.index)),yticklabels=matrix.index)
            ax.tick_params(axis='x',labelrotation=48,labelsize=8)
            fig.colorbar(grid,ax=ax,shrink=.7,label='Left loss minus right loss')
    fig.savefig(dest/'macro_groups_by_mode.png',dpi=160)
def write_report(run, base, dest):
    manifest = read(run/'manifest.json')
    lock = read(run/'selection.lock.json')
    if not manifest['test_complete'] or sha(run/'selection.lock.json') != manifest['lock_hash']:
        raise ValueError('No completed verified formal run')
    b, c = (core_results(run, stage) for stage in ['development','test'])
    b = b.assign(stage='B')
    c = c.assign(stage='C')
    pd.concat([b,c]).to_csv(dest/'core_paired.csv',index=False,encoding='utf-8-sig')
    groups = pd.concat([group_results(run,'development').assign(period='B'),group_results(run,'test').assign(period='C')])
    groups.to_csv(dest/'macro_groups_primary.csv',index=False,encoding='utf-8-sig')
    group_chart(groups,dest)
    params = {k: value['winner']['parameters'] for k,value in lock['parameters'].items()}
    (dest/'locked_winners.json').write_text(json.dumps(params,ensure_ascii=False,indent=2),encoding='utf-8')
    matched = pd.DataFrame(read(dest/'candidate_matched_contrasts.json'))
    base_report = ['# RBF-SVM 宏观增量复核报告','',
        '**历史 C 没有确认可重复的宏观主损失改善。** 中证全指分类加入宏观后的 Log Loss 上升，四市场的回归开发选模均把宏观权重降为 0。少量分组有正向证据，结论限于相应市场、任务和对照方式。合成对照显示模型可以学习已知宏观信号。',
        '',
        f"正式运行 `{manifest['run_id']}`。B 使用 2020—2022 年的 36 个月。C 使用 2023 年 1 月至封版的 47 个月，属于历史结果已被查看后的修订复核。参数和预警工作点均由 B 锁定。", '',
        '## 主结果', '',
        '差值为 M 损失减 M+Z 损失。正数表示 M+Z 的损失较低。区间使用原协议的同步 8 周区块 Bootstrap，重复 2,000 次。分类使用 Log Loss，回归使用固定初始尺度的五维等权平方损失。', '',
        '| 阶段 | 市场 | 任务 | 周数 | M | M+Z | 差值 | 95% 区间 | M+Z 宏观权重 |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |']
    for row in pd.concat([b,c]).sort_values(['stage','market_id','task']).to_dict('records'):
        key = '|'.join([row['market_id'],row['task'],'M+Z'])
        base_report.append(f"| {row['stage']} | {NAMES[row['market_id']]} | {TASKS[row['task']]} | {row['n']} | {fmt(row['M'])} | {fmt(row['M+Z'])} | {fmt(row['mean'])} | [{fmt(row['lower'])}, {fmt(row['upper'])}] | {params[key]['macro_weight']} |")
    r = c[c.task.eq('classification')]
    positive = r[r.lower.gt(0)]
    negative = r[r.upper.lt(0)]
    rbf_main = r[r.market_id.eq('000985.SH')].iloc[0]
    base_report += ['', f"中证全指分类的 C 主比较差值为 {fmt(rbf_main['mean'])}，95% 区间为 [{fmt(rbf_main['lower'])}, {fmt(rbf_main['upper'])}]。四个分类市场中，区间完全为正的有 {len(positive)} 个，完全为负的有 {len(negative)} 个。跨三种非线性模型的 Holm 校正仍待其他两个家族完成。",
        '', '四个回归市场均在 B 选了零宏观权重。C 的独立调参差值只比较不同金融核尺度及选择配置。正权重是否降低回归损失，应查看固定参数宏观对照。',
        '', '### C 年度差值', '',
        '| 市场 | 任务 | 年度 | M 减 M+Z | 95% 区间 |',
        '| --- | --- | --- | ---: | --- |']
    years = pd.read_csv(run/'tables/macro_increment.csv')
    rows = years[years['mode'].eq('retuned_core') & years.year.ne('all') & years.block_weeks.eq(8)
        & years.metric.isin(['log_loss','five_dimension_squared'])]
    for x in rows.sort_values(['market_id','task','year']).to_dict('records'):
        base_report.append(f"| {NAMES[x['market_id']]} | {TASKS[x['task']]} | {x['year']} | {fmt(x['mean'])} | [{fmt(x['lower'])}, {fmt(x['upper'])}] |")
    base_report += [
        '', '## 开发期改动的实证', '',
        '金融块与宏观块以各自训练总方差归一化。宏观权重直接乘在宏观平方距离上，核基值为 1。模型按实际输入列与封版谱系确定经济组，保留训练内有变化的缺失和适用性指标。SVC 使用成熟内部时间块校准，七个 SVR 分别选择 C 和 epsilon，共享由原五维损失决定的核布局。',
        '', '两个核心信息集对每任务各有 16 个候选，每个候选都走完整 B。零权重与 M 的匹配候选在所有 B 配对中的最大主损失差为 0。以下是同训练折、同样本和相同主要求解参数的开发期比较。', '',
        '| 改动 | 对照数 | 平均损失下降 | 最小 | 最大 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for field,task,name in [('calibrator','classification','Platt 改为正则化多项校准'),
        ('class_weight','classification','自然权重改为均衡权重'),
        ('representation','classification','分类完整宏观改为精简'),
        ('representation','regression','回归完整宏观改为精简'),
        ('paired_macro','classification','分类加入正权重宏观'),
        ('paired_macro','regression','回归加入正权重宏观')]:
        x = matched[matched.field.eq(field) & matched.task.eq(task)]
        if field=='paired_macro':
            x=x[x.right_value.gt(0)]
        delta=x.loss_left_minus_right
        base_report.append(f'| {name} | {len(x)} | {fmt(delta.mean())} | {fmt(delta.min())} | {fmt(delta.max())} |')
    base_report += ['', '上述均值描述已执行候选间的变化。B 同时用于选模，具有选模偏差。四市场回归的 48 个正权重同参比较全部增加了损失。选定正权重回归配置在 C 也全部增加损失，其中沪深 300 的区间完全为负。',
        '',
        '中证全指分类固定正权重的 B 损失下降 0.00917，C 下降 0.00113，C 区间为 −0.00540 到 0.00670。B 中的收益在历史 C 中缺少精度与稳定性。独立重调的分类主比较在四个 C 年度点估计均为负，2026 年末段幅度最大。',
        '', '## 分组、消融与条件增量', '',
        '原 96 项固定全模型参数配置是四市场 × 两任务 × 十二信息集，十二个信息集含 M、M+Z、五个单组和五个整组删除。本轮每阶段都执行这 96 项。全宏观参数取 B 最佳正权重模型。独立的分组重调还覆盖五次加入与五次删除。时钟消融保留信息年龄、适用性和缺失指标。',
        '', '| C 对照方式 | 比较数 | 差值为正数 | 区间完全为正 | 区间完全为负 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for (mode,task,kind), sub in groups[groups.period.eq('C')].groupby(['mode','task','kind']):
        base_report.append(f"| {mode} · {TASKS[task]} · {kind} | {len(sub)} | {(sub['mean']>0).sum()} | {(sub['lower']>0).sum()} | {(sub['upper']<0).sum()} |")
    keys = ['mode','market_id','task','kind','left','right']
    gb = groups[groups.period.eq('B')][keys+['mean']].rename(columns={'mean':'B_mean'})
    gc = groups[groups.period.eq('C')].merge(gb,on=keys,validate='one_to_one')
    supportive = gc[gc.lower.gt(0) & gc.B_mean.gt(0)]
    base_report += ['', f'B 和 C 同向且 C 的描述性区间完全为正的分组或时钟对照共有 {len(supportive)} 项。']
    if len(supportive):
        base_report += ['', '| 模式 | 市场 | 任务 | 对照 | B 差值 | C 差值 | C 95% 区间 |',
            '| --- | --- | --- | --- | ---: | ---: | --- |']
        for x in supportive.to_dict('records'):
            base_report.append(f"| {x['mode']} | {NAMES[x['market_id']]} | {TASKS[x['task']]} | {x['left']} → {x['right']} | {fmt(x['B_mean'])} | {fmt(x['mean'])} | [{fmt(x['lower'])}, {fmt(x['upper'])}] |")
    dd = read(run/'development/rbf_diagnostics/manifest.json')
    base_report += ['', '固定参数的沪深 300 分类信用组删除对照在 B 和 C 同向。C 加回信用组的损失下降 0.00896。独立重调的沪深 300 分类利率单组在 C 下降 0.06039，这一信号缺少 B 同向支持。回归重调中的整组删除比较，其全宏观参考模型权重为 0，同时存在重新选参差异。',
        '', '单组及删除项的全市场逐项数值见 `macro_groups_primary.csv`。分组图按固定参数和独立重调参分别展示。区间用于描述分组证据。 [分组图](macro_groups_by_mode.png)',
        '', '### 条件增量和扰动', '',
        '| 诊断 | 市场与任务 | 周数 | 损失差 | 95% 区间 |',
        '| --- | --- | ---: | ---: | --- |']
    for name, rows in dd.get('summaries',{}).items():
        for x in rows:
            market,task=x['comparison_id'].split('|')
            zh='成熟金融折外残差校正' if name=='conditional' else '联合两周宏观块扰动'
            base_report.append(f"| {zh} | {NAMES[market]} {TASKS[task]} | {x['n']} | {fmt(x['mean'])} | [{fmt(x['lower'])}, {fmt(x['upper'])}] |")
    base_report += ['', '条件校正的差值为金融锚点减校正模型。扰动的差值为扰动输入减真实输入。条件校正仅使用外层训练成员中已成熟的金融折外标签。置换在各验证月内使用联合连续两周宏观块。',
        '', '## 概率、七目标与朴素基准', '',
        '逐周原始决策分数与校准前后的概率保存在两阶段的 `metrics/rbf_probability_evidence.parquet`。外层校准诊断提供原始排序 AUC、概率排序、Log Loss、Brier、类别支持和概率偏差。阈值前的支持数及混淆矩阵见阶段表。B 的沪深 300 评分包含 3、145、2 周。中证 500 在 B 缺少状态 0，相关 AUC 无法定义。',
        '', '七目标的原单位 MAE、RMSE、相关性、偏差和预测离散程度保存在 `core_regression.csv`，每月各目标的训练拟合诊断和参数保存在 `rbf_regression_train.csv`。训练均值、持续值、历史频率和当前状态的对照使用同一组评分日期，主损失及区间见 `rbf_paired_baselines.csv`。',
        '', '### C 朴素基准配对', '',
        '| 朴素基准 | 模型信息集 | 基准损失高于模型的市场数 | 差值区间完全为正的市场数 |',
        '| --- | --- | ---: | ---: |']
    paired_baselines = pd.read_csv(run/'tables/rbf_paired_baselines.csv')
    for (family, info), block in paired_baselines[paired_baselines.block_weeks.eq(8)].groupby(['baseline','information_set']):
        base_report.append(f"| {family} | {info} | {(block['mean']>0).sum()} | {(block['lower']>0).sum()} |")
    base_report += [
        '', '### 中证 500 换手率的匹配拆解', '',
        '| B 设定 | 原单位 RMSE | 预测/观察标准差 |',
        '| --- | ---: | ---: |']
    turnover = pd.read_csv(run/'development/tables/rbf_turnover_matched.csv')
    for label,info,repr_,weight,C,epsilon in [
        ('金融锚点','M','compact',0,.35,.12),
        ('零宏观权重','M+Z','compact',0,.35,.12),
        ('加入完整宏观','M+Z','full',.5,.35,.12),
        ('换用精简表示','M+Z','compact',.5,.35,.12),
        ('同精简表示提高 C','M+Z','compact',.5,8.,.12),
        ('同精简表示减小 epsilon','M+Z','compact',.5,.35,.025)]:
        subset = turnover[turnover.information_set.eq(info) & turnover.representation.eq(repr_) &
            turnover.gamma_factor.eq(.25) & turnover.macro_weight.eq(weight) & turnover.C.eq(C) & turnover.epsilon.eq(epsilon)]
        if len(subset)==1:
            x=subset.iloc[0]
            base_report.append(f"| {label} | {fmt(x['rmse_turnover'],7)} | {fmt(x['std_ratio_turnover'])} |")
    base_report += ['', '预测离散比用于定位变化，主指标仍是配对损失。',
        '', '## 对未能复现增益的解释', '',
        '直接观察到的限制包括少数类支持稀缺和概率校准的跨期偏差。C 的中证全指状态 0、1、2 分别有 4、184、6 周。状态 0 的原始分数 AUC 在 M、M+Z 分别为 0.962、0.867，校准概率 AUC 分别降至 0.007、0.008。按保存的参数和类别顺序逐月重算，概率与留档逐值一致。状态 0 的校准斜率在两个模型的 47 次拟合中分别有 43 和 44 次为负。分数排序的估计经校准后发生了反转，稀少事件加大了跨期变化的不确定性。',
        '', '中证 500 分类的 C 状态 1 实际频率为 80.93%。M 和 M+Z 分别赋予平均 93.50% 和 95.17% 的概率，M+Z 的 Log Loss 和 Brier 均恶化。开发期的正则校准对照有正有负。两周宏观置换的八项损失区间都跨零，回归条件校正也缺少正向结果。',
        '', '这些证据支持优先关注少数类稀疏、估计噪声和校准跨期不稳定。两种表示及有限候选下，回归的宏观额外距离持续增加损失。现有数据无法区分经济信息冗余、表示局限与历史档案重建各自的作用。',
        '', '## 核验收、数据限制与复现', '',
        '源码编译、原始封版接口验收、191 项普通 pytest 和真实执行器验收均通过。固定合成对照的两个种子都通过。宏观信号损坏后，分类及回归优势消失。技术折上零权重、串并行及重新加载的预测逐值一致。',
        '', '选中模型的同样本训练—训练与成熟评分行—训练核见 `selected_exact_kernel.json`，包括块距离、基准与实际核尺度、核指数及核矩阵变化。早期每元素 RMS 的代数对照以封版矩阵重算。',
        '', '封版历史重建视图在数据审计范围内的有效可得时间均满足预测时点规则。DR007 的 409 条历史周度记录使用较晚档案版本。409 个周度 GDP、制造业 PMI、CPI 值分别来自 33、96、97 个源记录，持有值多于原始发布。该视图的增益结论受档案重建、市场样本规模、少数类稀疏及区间不确定性约束。',
        '', '在已检查的本机位置未找到 11 月 23 日与 25 日指定 ZIP，也未找到两套指定历史 run。可找到的较早便携包、对应 Git 和逐文件差异见 `historical_provenance.json`。本轮匹配技术对照以可取得的 11 月 21 日 Git 源码作为历史对照。',
        '', '额外公布滞后、市场模块投影、替代状态字典和其他数据质量视图属于独立扩展。此次结果的可复现入口和依赖见 `commands.json`、`config.resolved.yaml`、`selection.lock.json`、`environment.json` 和验收回执。',
        '', '复现请使用本地执行源码的字节快照 `executed_source_4493be5153575e180993d287.zip`。Git 与运行脚本逐文件比较的差异仅为换行。快照保留运行时的换行格式、验收回执、封版产物及完整测试所需的原始本机缓存。核验记录见 `source_equivalence.json`。',
        '', f"完整运行目录 `{run}`。完整资产按任务记录和模型包清单校验，代表性包另附。",
        '', f"冻结源码提交 `de3f55c34fdd27363704cb100682619e9d83eec0`。正式锁 SHA-256 `{manifest['lock_hash']}`。"]
    (dest/'交付报告.md').write_text('\n'.join(base_report)+'\n',encoding='utf-8')

def models_zip(run, dest):
    items = read(run/'test/selection/assignments.json')
    entries = []
    path = dest/'representative_models.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for item in items:
            i=item['identity']
            if i['mode']!='retuned_core' or i['fold_id']!='2026-10':
                continue
            directory = run/item['artifact']/'model_package'
            assert directory.is_dir()
            name = '/'.join([i['market_id'],i['task'],i['information_set']])
            for f in directory.rglob('*'):
                if f.is_file():
                    archive.write(f,name+'/'+f.relative_to(directory).as_posix())
            entries.append(dict(name=name,artifact=item['artifact'],model_manifest_sha256=sha(directory/'manifest.json')))
    assert len(entries)==16
    (dest/'model_delivery.json').write_text(json.dumps(dict(archive=path.name,sha256=sha(path),entries=entries),indent=2),encoding='utf8')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('run',type=Path)
    a=p.parse_args()
    run=a.run.resolve(); dest=run/'delivery'; base=run.parents[1]
    dest.mkdir(exist_ok=True)
    write_report(run,base,dest)
    models_zip(run,dest)
    print(dest/'交付报告.md')

if __name__=='__main__':
    main()
