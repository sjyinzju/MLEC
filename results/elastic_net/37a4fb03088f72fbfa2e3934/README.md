# MLEC Elastic Net 完整 B＋C 复跑归档

- [最终验收](最终验收.md) · [开发阶段 B](development/report.md) · [测试阶段 C](report.md)
- [正式运行清单](manifest.json) · [锁定参数](selection.lock.json) · [独立核验](independent_verification.json)
- [固定参数宏观组结果](tables/macro_groups.csv) · [同参敏感性结果](tables/fixed_parameter_sensitivity.csv)
- [测试评分](test/metrics/selected_scores.parquet) · [测试逐周配对损失](test/losses/paired_differences.parquet) · [任务索引](tasks.parquet)
- [开发评分](development/metrics/selected_scores.parquet) · [开发逐周配对损失](development/losses/paired_differences.parquet)
- [开发预警曲线](development/tables/warning_curves.csv.gz) · [测试预警曲线](tables/warning_curves.csv.gz)

运行 ID 为 37a4fb03088f72fbfa2e3934，状态为 EXPERIMENT_COMPLETE。测试完成了 47 个折中的 96 个固定宏观配置。具体口径和结果见验收报告。

复现需要项目的同一份封版数据及 [运行环境](environment.json)。[训练源文件快照](source_snapshot/snapshot.json) 记录了精确文件和训练提交 0dd6f4d0b69a31a9e809fe9ef23c8a60276d0691。[报表修复记录](reporting_recovery.json) 指向提交 62559863d0814a31701863334eb97108b5a25e39，该修复从已保存的工件重建报表，未重新拟合。[原始运行配置的可移植副本](config.resolved.yaml) 把本机输入、输出目录改为项目相对路径。

[归档清单](EXPORT_MANIFEST.json) 记录每个文件的 SHA-256、大小和原始来源。两个预警曲线和 [本机全量校验清单](SHA256SUMS.txt.gz) 可用 gzip 解压。全量校验清单用于核查本机原件，其中的逐次拟合对象、单任务原始记录、日志和恢复文件仍随本机结果保留。GitHub 保留报告、图表、评分与配对损失、任务聚合索引、锁定参数、审计和源码快照。归档版验收报告链接到本页和压缩后的校验清单。
