# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

机器可读字段字典为 `data/metadata/field_dictionary.parquet`，包含全部物理字段、类型、源单位、解释、必需标记、全量空值数与定义证据。宏观value的单位与measure_type按series_id定义。

| file | purpose |
| --- | --- |
| dataset_registry.json | 唯一权威路径、主键、行数、范围和整体限制 |
| schema_registry.json | 每个权威表完整物理Schema |
| field_dictionary.parquet | 逐字段类型、单位、解释、空值与证据 |
| source_registry.parquet | 来源、快照、成功/失败请求与哈希 |
| data_lineage.parquet | 原始证据、记录父项和转换边 |
| quality_registry.parquet | 数据集认证状态，须连同逐行质量和问题表读取 |

必需字段中仍待补充的来源单位/定义：

| dataset_id | field | unit | definition |
| --- | --- | --- | --- |
| exchange_activity_sz | amount | SOURCE_DEFINITION_REQUIRED | 成交金额 |
| exchange_activity_sz | vol | SOURCE_DEFINITION_REQUIRED | 成交量 |
| exchange_activity_sz | total_mv | SOURCE_DEFINITION_REQUIRED | 总市值 |
| exchange_activity_sz | float_mv | SOURCE_DEFINITION_REQUIRED | 流通市值 |
