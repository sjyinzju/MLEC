# ECON3059 中国宏观信息与A股风险状态研究

当前阶段仅建设研究数据基础，冻结协议为 `market-research-v2.0.0`。本轮数据版本 `data-foundation-v3.0.0` 的**全量验收仍为FAIL**：41个经济概念及61个分口径候选序列已核查，重大历史缺口和未认证版本见[最终验收](reports/data_quality/final_data_acceptance.md)，不能因管线可运行而认为全部数据已齐备。

入口是 `python -X utf8 -m scripts.data_foundation_v3.cli`，只处理采集、标准化、核对、特征、样本、验证和报告。本轮禁止模型训练、调参、benchmark和2023+最终实验。

- [项目结构与迁移](docs/project_structure.md)
- [逐期完整率](reports/data_quality/macro_completeness.md)
- [字段字典](docs/data_dictionary.md)与[数据契约](docs/data_contracts.md)
- [来源证据](docs/data_sources.md)与[剩余限制](docs/remaining_data_limitations.md)
- [完整复现命令](docs/data_reproducibility.md)
- [历史探索成果说明](docs/historical_exploration.md)

快速数据检查：

```powershell
python -X utf8 -m pytest tests/data_foundation_v3 -q
python -X utf8 -m scripts.data_foundation_v3.cli validate
python -X utf8 -m scripts.data_foundation_v3.cli verify-lineage
```

权威数据均在data/：raw保存不可变来源；standardized/macro/v3保留所有分级事实；research_v2保存冻结市场；features/v3保存周度特征和lineage；datasets/foundation_v3保存24套可组合数据集；metadata保存注册表、字典、日历和资格依据。数据目录中的候选值必须按quality_status和certification_status使用。

仓库从实际路径解析根目录；E:/QuantData、E:/quant仅只读。课程材料已移至docs/course，课题Word在docs/research_design，旧交付指针在docs/archive；完整迁移证据在audit/data_foundation_v3。旧市场数据、模型与实验成果保留。大原始快照部分被Git忽略，离线复现必须提供来源清单中的实际文件及哈希。
