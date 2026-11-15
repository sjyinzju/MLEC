# 当前字段字典

机器可读权威字典为 data/metadata/field_dictionary.parquet；包含数据集、字段、物理类型、单位、含义、必需标记、全表空值数和来源定义。完整 schema 在 schema_registry.json，序列的频率、币种、期间、统计范围在 config/data/macro_requirements.json。

遗留 evidence_path 表示原来源对象的定位标识，不代表文件仍存在。原始对象已按保留政策删除；来源链接见 source_registry.parquet，范围定义见 scope_definitions.json，修复的数值父记录在 metadata 中按主题保存。可得时间/采集时间/观察日期不可互换。

完整性与使用限制以 reports/data_quality/final_database_report.md 为准。冻结 v2 的原字段定义和标签不因本字典而改写。
