# 数据结构

当前数据版本 practical-research-data-v5，物理路径沿用 data/standardized/{market,macro}/v4。唯一权威表、字段和主键见 data/metadata/dataset_registry.json、schema_registry.json 和 field_dictionary.parquet。整体状态 UNRESOLVED_REQUIRED_DATA；合格指标可独立使用。

正式股票入口为 stock_daily_observations、stock_daily_basic_observations、stock_adjustment_observations、stock_limits_observations；无后缀的重复供应商中间表已清理。证券身份通过 stock_master_history 的法律身份和代码有效区间解释。供应商扩展表的历史代码别名应先映射法律身份，再连接行情。

data/research_v2、config/research_v2、既有模型与正式研究成果冻结。data/features/{market,macro}/v4 和 data/datasets 下的 v4 配置、资格表是当前扩展入口。早期实际实验使用的 v1 特征与样本清单保留；没有用于正式实验的旧 v3 派生副本已清理。

原始下载、运行记录、大型审计副本和复现备份不属于交付；精简来源/公式/缺口和验收摘要在 data/metadata。最终结论见 reports/data_quality/final_database_report.md。
