# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

`data/raw` 保存不变供应商/公告快照；`standardized/market/v4` 与 `standardized/macro/v4` 保存新标准层；`data/research_v2` 保持冻结；`data/features/{market,macro}/v4` 保存连续扩展及四种时点视图；`data/datasets` 保存特征集配置与资格掩码，避免重复复制整张矩阵。

股票行情三张正式观测入口是 `stock_daily_observations`、`stock_daily_basic_observations`、`stock_adjustment_observations`；涨跌停正式入口为 `stock_limits_observations`，特殊规则证据为 `stock_limit_rule_evidence.parquet`。同目录下不带 `_observations` 的表是可追溯供应商中间层，不是第二权威。最终消费路径以dataset_registry为准。既有路径不被删除，v3注册表和被替换文档在 `data/archive/data-foundation-v3` 按原字节保存。

来源失效时离线重建仍用已保存快照；源信息本身不足时保留QUALIFIED/FAIL。没有把整个QuantData复制进项目，也没有修改外部目录。
