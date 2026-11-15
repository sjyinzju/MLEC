# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

| check | name | execution | data_status | seconds |
| --- | --- | --- | --- | --- |
| 1 | market_primary_keys | PASS | QUALIFIED | 9.06 |
| 2 | seven_index_calendar_coverage | PASS | PASS_FOR_DATE_COVERAGE_ONLY | 0.05 |
| 3 | stock_identity_listing_and_suspension | PASS | QUALIFIED | 0.18 |
| 4 | constituent_temporal_validity | PASS | QUALIFIED | 0.05 |
| 5 | stock_returns_and_factors | PASS | QUALIFIED | 0.29 |
| 6 | breadth_liquidity_and_correlation | PASS | QUALIFIED | 3.8 |
| 7 | all_macro_candidate_periods | PASS | FAIL | 0.04 |
| 8 | macro_source_value_review | PASS | QUALIFIED | 5.25 |
| 9 | macro_release_and_vintage_times | PASS | QUALIFIED | 0.08 |
| 10 | cross_source_conflicts | PASS | FAIL | 0.0 |
| 11 | units_and_statistical_definitions | PASS | QUALIFIED | 1.12 |
| 12 | frozen_sample_asof_join | PASS | QUALIFIED | 4.91 |
| 13 | no_future_information_policy | PASS | QUALIFIED | 4.38 |
| 14 | real_historical_truncation | PASS | PASS_UNDER_DECLARED_RECONSTRUCTION_POLICY | 5.51 |
| 15 | future_data_perturbation | PASS | PASS_UNDER_DECLARED_RECONSTRUCTION_POLICY | 9.26 |
| 16 | source_hashes_and_lineage | PASS | QUALIFIED | 15.97 |
| 17 | sample_ids_and_configurable_interface | PASS | PASS | 3.58 |
| 18 | frozen_protocol_labels_folds_hashes | PASS | PASS | 32.13 |
| 19 | external_readonly_integrity | PASS | PASS | 20.58 |
| 20 | offline_reproduction | PASS | Reproduction does not certify unresolved source completeness or first-vintage availability. | 0.0 |

观察期、市场交易日、公告时间、实际版本可得时间、下载时间和成分生效时间分别保存。只有 `research_available_at <= asof_time` 的许可版本可进入对应视图。`quote_reconstructed` 对 DR007 明确使用另存的历史收盘可得假设；其真实版本可得时间仍保留，不能称为严格PIT。市场 v2 和 v4 连续扩展均明确为历史报价重建。

公告日期未知时不得由 URL 年份、文件名或观测月猜测。官方后期年报只能在年报发布日期后使用；同一时刻上载的海关月报按已证明的刊期顺序保存。LPR 月末是归档月份，实际定盘在 `observation_date`；春节前发布的 PMI 按原公告日期使用。

统一输入资格（H20 combined风险集）：

| dataset_id | macro_quality | rows | eligible_h20 |
| --- | --- | --- | --- |
| M | strict | 599 | 450 |
| growth | strict | 599 | 416 |
| prices | strict | 599 | 450 |
| credit | strict | 599 | 249 |
| rates | strict | 599 | 0 |
| external | strict | 599 | 0 |
| all_candidates | strict | 599 | 0 |
| M | conservative | 599 | 450 |
| growth | conservative | 599 | 416 |
| prices | conservative | 599 | 450 |
| credit | conservative | 599 | 356 |
| rates | conservative | 599 | 2 |
| external | conservative | 599 | 423 |
| all_candidates | conservative | 599 | 2 |
| M | quote_reconstructed | 599 | 450 |
| growth | quote_reconstructed | 599 | 416 |
| prices | quote_reconstructed | 599 | 450 |
| credit | quote_reconstructed | 599 | 356 |
| rates | quote_reconstructed | 599 | 301 |
| external | quote_reconstructed | 599 | 423 |
| all_candidates | quote_reconstructed | 599 | 232 |
| M | latest_at_retrieval | 599 | 450 |
| growth | latest_at_retrieval | 599 | 416 |
| prices | latest_at_retrieval | 599 | 450 |
| credit | latest_at_retrieval | 599 | 356 |
| rates | latest_at_retrieval | 599 | 2 |
| external | latest_at_retrieval | 599 | 423 |
| all_candidates | latest_at_retrieval | 599 | 2 |

样本从未因缺失被删除。450是冻结H20标签与风险集的共同资格上限，并非599行被删成450行。信用组原先被互斥社融范围共同非空要求压缩，本轮按概念选择已公布的合法范围；M1新旧口径互斥选择。2015年季度社融存量使用既有季度150日陈旧期限。利率组的保守版本仍受DR007历史原始版本和LPR制度生效前不适用限制；显式报价重建视图单列。增长组因1—2月合并公布和预设陈旧期限仍存在间隔，不为增加样本数任意放宽期限。

资格表中的eligible默认要求各概念最新值合格；previous/change的首期、跨年累计重置或口径切换缺失另列active_transforms_complete与eligible_with_complete_transforms。接口参数require_complete_transforms=True可收紧准入；逐单元feature_lineage保留缺失原因，未生效scope列是明确的结构空列，不能全表dropna或静默填充。

截断与扰动测试使用真实全候选事实、三个历史时点、七指数完整前缀；市场广度/Amihud/离散度对全部3095日独立重算，平均相关在三个真实完整截面以全部证券两两相关直接复核。结果详见 `audit/final_data_foundation/validation_results.json`，检查失败时以该文件为准。
