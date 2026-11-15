# ECON3059 中国宏观信息与 A 股风险状态研究

当前交付采用 `practical-research-data-v5`：保留处理后的数据和可直接读取的研究特征，接受有明确来源、口径和可得时间假设的历史重建数据。尚有真实缺口，整体状态为 **UNRESOLVED_REQUIRED_DATA**，已完整的指标可以独立使用。

- [最终数据库说明](reports/data_quality/final_database_report.md)
- [唯一权威数据注册表](data/metadata/dataset_registry.json)
- [宏观逐期完整性](data/metadata/final_foundation/data_requirements_matrix.parquet)
- [宏观完整性简表](data/metadata/macro_completeness.parquet)
- [字段字典](data/metadata/field_dictionary.parquet)
- [历史重建与来源规则](data/metadata/practical_research_policy.json)

金融市场数据在 `data/standardized/market/v4/`，宏观数据在 `data/standardized/macro/v4/`。目录中的 `v4` 是沿用的物理路径；权威路径和当前版本以注册表为准。

冻结协议 `market-research-v2.0.0` 的 599 个候选时点、H5/H20/H40 标签、风险集和时间折在 `data/research_v2/`。既有正式模型成果保留，本轮未训练模型、运行 Benchmark 或生成预测。

```python
from scripts.final_data_foundation.research_inputs import load_dataset

# M；返回 features、eligibility、targets、folds 和 feature_lineage。
market = load_dataset(quality="historical_reconstructed")
# M+Z_group；其余组为 growth、prices、rates、external。
credit = load_dataset(groups=["credit"], quality="historical_reconstructed")
# M+Z_custom；不同制度口径使用不同 series_id，不能跨口径计算变化。
custom = load_dataset(series=["cpi_yoy", "m2_yoy"],
                      quality="historical_reconstructed", horizon=20)
# M+Z：保留全部候选行，由 eligibility 明确标记可用样本。
joint = load_dataset(groups=["growth", "prices", "credit", "rates", "external"],
                     quality="historical_reconstructed")
```

`eligible` 不代表所有转换列都非空；需要上一期/变化项齐全时设置 `require_complete_transforms=True`。严格原始版本与历史重建是不同口径，不能混称严格 PIT。默认质量参数仍为 `conservative`，实际研究请明确选择所用口径。

```python
from scripts.final_data_foundation.membership import load_index_members
members = load_index_members("000300.SH", "2020-06-30 18:00",
                             mode="monthly_snapshot")
```

历史成分/权重按月度快照使用，默认最长沿用 45 天；不是精确逐日权重。`effective` 模式仅返回已收录公告支持的生效区间，公告目录不声称穷尽。日期不带时间时按当天零点查询。

原始数据由用户和同伴保管，仓库不交付原始 API 响应、网页、下载备份、运行日志和大型逐行审计副本。标准数据保留来源标识、时间假设和必要质量标记；不承诺删除原始材料后仍能逐字节离线重建。维护采集代码保留，重新采集需相应数据源和权限。

依赖见 `requirements-data-v4.txt`。大型金融标准分区和模型二进制不随 GitHub 克隆分发；注册表列出本地数据位置。`E:/QuantData`、`E:/quant` 为外部只读来源，不在清理范围内。
