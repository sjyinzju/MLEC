# ECON3059：宏观信息的 A 股风险增量预警价值

当前项目位于 D 盘课程目录，脚本以仓库根目录解析路径。`E:\QuantData` 与 `E:\quant` 仅作为只读来源。市场协议 `market-research-v2.0.0`、状态、阈值、样本 ID 与 H20 目标保持冻结。

研究入口是 `scripts/experiment_framework/cli.py`。全部算法共享 Dataset Loader、共同样本、年度扩展折、训练内预处理、配对评价。2023 年以后标签在新建建模数据集中隐藏；命令行不提供最终期训练/选择入口。

```powershell
python -X utf8 scripts/experiment_framework/cli.py validate-data
python -X utf8 scripts/experiment_framework/cli.py benchmark --stage development
python -X utf8 -m pytest tests/research_v2 tests/experiment_framework -q
```

完整数据重建、采集命令、环境与限制见 [复现说明](docs/reproducibility.md)。

- [数据修复与跨来源核对](reports/data_quality/macro_reconciliation.md)
- [逐指标覆盖和真实缺口](reports/data_quality/macro_coverage.md)
- [公告时间与修订证据](reports/data_quality/macro_pit_validation.md)
- [共同样本质量](reports/data_quality/joint_dataset_quality.md)
- [开发期实际结果](reports/benchmark/development_results.md)
- [实验协议](reports/benchmark/benchmark_protocol.md)
- [最终交付与验收](reports/research/engineering_handoff.md)

权威数据路径：`data/raw/macro/` 原始证据；`data/standardized/macro/` 标准事实与版本；`data/research_v2/` 冻结市场数据；`data/features/` 宏观周度特征；`data/datasets/` 共同样本；`data/metadata/` 注册表、字典与来源。

旧 `data_raw/`、`deliverables/` 数据已按哈希迁入不可变原交付快照；根目录原 ZIP 归档到 `data/raw/macro/original_submissions/packages/`。迁移记录在 `audit/framework/`。原研究报告保留于 `reports/research_v2/`，课件示例 `datacodes_lec3/` 和课题设计 Word 保持原位。

核心组使用逐期官方宏观公告及按报价日结束后可用的官方 Shibor 历史档案。后者缺更正版本日志，因此不能称为所有变量严格 PIT。进出口历史候选值尚未认证历史公告版本，DR007 尚无可验证长历史，不进入本轮主实验。所有缺口保留，不以未来值或相似指标填补。尚未提交或推送 Git。
