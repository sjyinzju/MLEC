# 项目目录与权威路径

本轮仅做数据工程。市场协议 market-research-v2.0.0、阈值、状态、标签、599 个周度样本与原时间折保持冻结；未运行模型、调参或预测实验。

迁移前记录 3895 个文件、1,020,840,876 字节。此次迁移 124 个文件，逐一核对哈希后处理旧路径；移除 44 个已核验的空目录。完整清单在 audit/data_foundation_v3/baseline.json 和 migration_manifest.json。

|路径|职责|
|---|---|
|README.md、requirements-research.txt、.gitignore|项目入口、依赖和版本控制规则|
|data/raw/macro|原交付包、官方/第三方原文、请求与响应快照|
|data/raw/market|市场来源证据；原冻结依赖继续按旧清单保留|
|data/standardized/macro/v3|事实、版本、发布日期事件；未准入候选仍保留并分级|
|data/research_v2|原冻结市场数据，权威值不改写|
|data/features/v3|三个质量等级的周频宏观特征和逐单元格lineage|
|data/datasets/foundation_v3|每等级8组数据集及资格表；共享原标签、时间折|
|data/metadata/foundation_v3|需求矩阵、序列字典、来源和数据集注册|
|data/metadata/market|SSE日历和时间折清单的新增权威数据路径；旧审计副本保留|
|data/archive/course_examples/lecture03|课程RData等数据，不作为本研究输入|
|docs/course、docs/research_design、docs/archive|课程代码、课题Word、旧交付指针及原始课程脚本|
|scripts/data_foundation_v3|本轮纯数据CLI；旧模块只复用数据变换|
|config/data|41个经济概念、分口径序列需求、质量政策、组配置、公开请求计划|
|audit/data_foundation_v3|迁移、来源、缺口、测试、完整性和复现证据；不是特征入口|
|reports/data_quality|本轮质量报告及之前历史报告；以final_data_acceptance.md为当前结论|
|experiments、artifacts/models、reports/benchmark|历史开发期探索成果，保留位置和字节，不作为本轮筛选依据|

datacodes_lec3 与 deliverables 的迁移不删除原始数据证据。课程knn脚本的旧macOS路径已修复，原脚本另存 docs/archive/course_original，课程模型未执行。尚未删除用途不明文件或外部项目文件。忽略的原始大文件仍需随快照备份，不能仅凭Git克隆复现。
