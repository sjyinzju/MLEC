# 项目入口

- data/standardized/{market,macro}/v4：当前金融、宏观标准表；唯一权威路径见 data/metadata/dataset_registry.json。
- data/features/{market,macro}/v4、data/datasets 下 v4：当前特征、资格表与读取配置。
- data/research_v2、config/research_v2：冻结样本、标签、风险集和时间折。
- data/metadata：简明注册/字典/来源、必要派生父值、真实缺口和验收汇总。
- scripts/final_data_foundation：数据维护与统一接口；其他旧模块保留必要处理代码。
- experiments、artifacts/models、reports/benchmark、reports/research_v2：已有正式成果，不在本轮重新运行。
- docs/course、docs/research_design、docs/archive/course_original、data/archive/course_examples：用户课程和课题材料，保留。
- reports/data_quality/final_database_report.md：唯一当前数据质量报告。

原始响应、运行日志、复现备份和大审计副本已清理。GitHub 不分发大型金融分区、模型二进制及本地依赖，不能仅凭克隆取得完整本地数据库。
