"""Render delivery tables from actual artifacts; no model selection."""
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.experiment_framework.common import ROOT,read_json,write_text,write_json,identity
from scripts.experiment_framework.dataset import load_dataset

def build():
    sets=read_json(ROOT/'config/experiments/feature_sets.json');rows=[]
    for name,s in sets.items():
        r={'feature_set':name,'status':s['status'],'sample_version':s['sample_version'],'features':len(s['columns']),'initial_candidate_weeks':s.get('initial_training_weeks')}
        if s['status']=='eligible':
            for year in [2020,2021,2022]:
                for role in ['train','validation']:
                    d=load_dataset(s['sample_version'],name,20,f'dev-{year}',role)
                    r[f'{year}_{role}']=len(d.y)
        rows.append(r)
    table=pd.DataFrame(rows);meta=pd.read_parquet(ROOT/'data/datasets/main_v1/common_samples.parquet')
    write_text(ROOT/'reports/data_quality/joint_dataset_quality.md','# 联合样本验收\n\n'+f'冻结周度候选 {len(meta)}；市场有效风险周 {int(meta.included_market.sum())}；核心宏观共同周 {int(meta.included_core.sum())}。这里包括未用于模型选择的 2023+ 候选结构；其新建标签列已隐藏。真正外层开发 OOF 受原时间折、标签成熟/边界 purge 约束，数量如下。\n\n'+table.to_markdown(index=False)+'\n\n核心组保留全部 99 个市场开发 OOF 周。增长/信用/full 组因历史公告覆盖、春节合并、陈旧上限而样本更短，均在相同版本重新训练 M；不得跨样本版本直接相减指标。每个样本的 risk_set、target_valid、included_market/core、macro_complete 和 joint_exclusion_reason 在对应共同样本表中；每条宏观缺失/陈旧原因在 macro_availability。初始候选计数并非每折可用训练计数，差额来自原标签成熟度边界。\n\nas-of 防泄漏测试覆盖延迟发布、旧期修订、未来扰动、历史截断；所有派生记录保留使用的 source_record_ids，可得时间取所用版本时间最大值。日频窗口基于 SSE 开放日，缺少报价的窗口不补值。标准化、缺失填充、方差过滤和类别编码仅在训练折拟合。原数据/标签/协议哈希另验收。\n')
    write_json(ROOT/'audit/framework/joint_counts.json',rows)
    original=pd.read_parquet(ROOT/'data/raw/macro/original_submissions/v1/deliverables/macro_raw.parquet')
    new=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    comparison=[]
    for sid,g in new.groupby('series_id'):
        old=original[original.series_id.eq(sid)];accepted=g[g.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]
        comparison.append({'series_id':sid,'original_rows':len(old),'original_start':str(old.period_end.min())[:10] if len(old) else '', 'original_end':str(old.period_end.max())[:10] if len(old) else '', 'new_fact_rows':len(g),'accepted_rows':len(accepted),'accepted_periods':accepted.period_end.nunique(),'accepted_start':str(accepted.period_end.min())[:10] if len(accepted) else '', 'accepted_end':str(accepted.period_end.max())[:10] if len(accepted) else ''})
    comparison=pd.DataFrame(comparison);comparison.to_csv(ROOT/'audit/framework/coverage_before_after.csv',index=False,encoding='utf-8-sig')
    latest=ROOT/'experiments/registry/latest.json'
    if not latest.exists():return
    run_id=read_json(latest)['run_id'];run=read_json(ROOT/f'experiments/registry/{run_id}.json')
    if identity(run.get('dataset_registry',{}))!=identity(read_json(ROOT/'data/metadata/dataset_registry.json')):
        print('Joint report complete; benchmark is from a different dataset, handoff deferred');return
    metrics=read_json(ROOT/f'experiments/metrics/{run_id}.json')
    from scripts.plot_benchmark import build as plot
    plot(run_id)
    probability_report=ROOT/'reports/benchmark/probability_evaluation.md'
    content=probability_report.read_text(encoding='utf-8')
    if 'core_calibration.png' not in content:write_text(probability_report,content+'\n![Core calibration curves](figures/core_calibration.png)\n\nNative probabilities are primary. Dashed calibrated curves are diagnostics; bins may be sparse. PDF export is available beside the PNG.\n')
    core=pd.DataFrame(metrics['probability_and_events']);core=core[core.sample_version.eq('common_core_v1')&core.feature_set.isin(['M','M_plus_Z_core'])]
    coretable=core[['algorithm','feature_set','n','brier','log_loss','detected_events','eligible_events','lead_mean']].to_markdown(index=False)
    paired=pd.DataFrame([{'algorithm':p['algorithm'],**p['delta_brier']} for p in metrics['paired'] if p['feature_set']=='M_plus_Z_core'])
    reproducible=read_json(ROOT/'audit/framework/reproducibility.json') if (ROOT/'audit/framework/reproducibility.json').exists() else {'status':'pending'}
    tests=ROOT/'audit/framework/tests.xml';test_result='未生成'
    if tests.exists():
        import xml.etree.ElementTree as ET
        s=ET.parse(tests).getroot().find('testsuite');test_result=f"tests={s.get('tests')}, failures={s.get('failures')}, errors={s.get('errors')}, skipped={s.get('skipped')}"
    write_text(ROOT/'reports/research/engineering_handoff.md','# ECON3059 工程交付与验收\n\n'+f'当前运行 `{run_id}`。本报告由真实产物生成；2023+ 未用于模型训练选择。\n\n## 1. 文件与目录治理\n\n原宏观交付完整快照和同伴脚本在 data/raw/macro/original_submissions；原 ZIP 逐哈希归档到 packages。原目录保留文档指针。冻结市场 89 个协议/数据/审计产物无变化；原采集项目只读。原课程示例和设计 Word 保留，未重新执行全量原始市场采集。\n\n## 2. 宏观数据质量\n\n原包 '+str(len(original))+' 条、'+str(original.series_id.nunique())+' 个序列；现标准事实 '+str(len(new))+' 条、'+str(new.series_id.nunique())+' 个序列（含合法多版本及隔离记录）。这些不是全部可训练行。核心五条月度序列 2014-12—2022-12 逐月官方公告已覆盖，Shibor 使用明确降级的官方报价档案。\n\n'+comparison.to_markdown(index=False)+'\n\n逐序列实际缺口和准入状态见 macro_coverage；语义修复、源公告和交叉核对见 macro_reconciliation；日期与修订限制见 macro_pit_validation。不能将原覆盖长短当作原数值可信证明。\n\n## 3. 联合研究数据集\n\n'+table.to_markdown(index=False)+'\n\n核心保留 450 个市场有效周，开发期真正 OOF 为 99 周，M 和 M+Z 样本/标签/折完全配对。各组 manifest 和逐宏观可得性明细保存排除理由。\n\n## 4. 预测框架\n\n四类模型共享 Dataset Loader、训练内预处理、标签成熟约束、年度扩展内外层折、固定搜索预算、模型保存/加载、概率/事件/配对评价。特征注册表可切换经济组、完整组与核心组消融。参见 docs/experiment_framework.md。\n\n## 5. 真实开发期 Benchmark\n\n'+coretable+'\n\n核心 Brier 配对增益（M 减 M+Z）：\n\n'+paired.to_markdown(index=False)+'\n\n事件阈值按每年最多两个误报周在开发期选择，因此开发预警命中偏乐观。区间小样本且未校正多重比较；不据此宣称最终期增量价值。完整各组结果、校准、可靠性和事件明细见 reports/benchmark 与 experiments/metrics。\n\n## 6. 自动测试与复现\n\n'+test_result+'。重跑状态：`'+str(reproducible)+'`。原市场核心由冻结日度数据重建到观测、状态、事件、周度特征、目标与折并比较；未宣称外部原始全量采集已重跑。运行命令及依赖见 docs/reproducibility.md。\n\n## 7. 研究限制与后续\n\n主核心可开展受限定数据版本下的开发配对研究，不能标成所有变量严格 PIT。进出口历史版本未认证、DR007 无可靠长历史、LPR/M1 新定义历史短，不能强行进入主组。最终期需冻结主模型、宏观组、校准、阈值和稳健性方案后单独评价；当前保留隔离。详见 docs/research_limitations.md。未提交或推送 Git。\n')

if __name__=='__main__':build();print('Reports updated')
