# 市场侧正式处理运行摘要

本轮已实现并运行完整真实数据流水线，协议`market-research-v2.0.0`。没有训练/调参/回测，没有宏观有效性结果。

| 产物 | 行数 | 列数 | 路径 |
| --- | --- | --- | --- |
| dimension_labels_daily | 2850 | 14 | data\research_v2\dimension_labels_daily.parquet |
| fold_membership | 71544 | 10 | data\research_v2\fold_membership.parquet |
| future_outcomes_weekly | 599 | 14 | data\research_v2\future_outcomes_weekly.parquet |
| market_daily_clean | 2850 | 34 | data\research_v2\market_daily_clean.parquet |
| market_features_weekly | 599 | 79 | data\research_v2\market_features_weekly.parquet |
| market_features_weekly_with_proxies | 599 | 105 | data\research_v2\market_features_weekly_with_proxies.parquet |
| market_observations_daily | 2850 | 66 | data\research_v2\market_observations_daily.parquet |
| prediction_targets_weekly | 1797 | 36 | data\research_v2\prediction_targets_weekly.parquet |
| risk_episodes | 67 | 29 | data\research_v2\risk_episodes.parquet |
| sample_to_event | 903 | 11 | data\research_v2\sample_to_event.parquet |
| state_labels_daily | 2850 | 36 | data\research_v2\state_labels_daily.parquet |
| stock_market_proxies_daily | 2850 | 22 | data\research_v2\stock_market_proxies_daily.parquet |

来源：9个依赖接口、登记active文件哈希冻结，非递归拼库。主序列2850日，599个完整周候选，586个核心历史特征完整周，582个历史+20日未来窗口候选，450个主风险集且标签完整周；有效主时点2015-04-10—2026-08-21。末日标签成熟时间按完整期限对称处理。

实际阈值：年化波动28.8522%，20日窗口最大回撤7.6578%，1199个初始期日观测。初始/开发状态事件和单因素敏感性见label_validation_report，测试细节独立heldout，不作选择。

验证：23项公式/事件单元测试通过；真实历史截断、未来扰动、参考阈值不变、全部折成熟度和完整主流程语义复现通过。折计划48个，折成员71544行。检查证据在audit/research_v2/validation_checks.json和unit_tests.xml。

新增产物预算2GiB、安全余量5GiB；当前统计产物约156.0MiB（本摘要生成前），磁盘空余28.0GiB。股票代理临时矩阵约242MiB，已关闭并仅清理本轮自建文件；没有保存股票两两相关矩阵。最终精确体积见日志run_complete。

复现（无需安装依赖，原环境只读使用，源目录不写pycache）：

```powershell
E:\quant\.venv\Scripts\python.exe -B -X utf8 E:\MLEC\scripts\research_v2\run_pipeline.py --stage all
```

统一入口先检查源哈希与冻结配置，复用校验通过的检查点；`--force`可完整重算。日志位于audit/research_v2/logs；输入/输出哈希、逐查询SQL、清单和字段字典均已保存。旧审计与源项目没有被改写；主注册表大小/mtime复核一致。

限制：历史重建不是严格历史版本PIT；沪深股票池/代码史与部分缺行情未完全认证，流动性和结构为PROXY；未验证宏观公告、覆盖或增量预测效果；事件数量有限、周目标重叠，不能用阳性周数冒充独立事件数。停止在市场侧研究数据和报告交付，不进入模型或类JEV开发。
