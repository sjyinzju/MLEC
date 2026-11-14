# ECON3059 工程交付与验收

当前运行 `dev-e47c442b6de1233e`。本报告由真实产物生成；2023+ 未用于模型训练选择。

## 1. 文件与目录治理

原宏观交付完整快照和同伴脚本在 data/raw/macro/original_submissions；原 ZIP 逐哈希归档到 packages。原目录保留文档指针。冻结市场 89 个协议/数据/审计产物无变化；原采集项目只读。原课程示例和设计 Word 保留，未重新执行全量原始市场采集。

## 2. 宏观数据质量

原包 12417 条、19 个序列；现标准事实 36026 条、32 个序列（含合法多版本及隔离记录）。这些不是全部可训练行。核心五条月度序列 2014-12—2022-12 逐月官方公告已覆盖，Shibor 使用明确降级的官方报价档案。

| series_id             |   original_rows | original_start   | original_end   |   new_fact_rows |   accepted_rows |   accepted_periods | accepted_start   | accepted_end   |
|:----------------------|----------------:|:-----------------|:---------------|----------------:|----------------:|-------------------:|:-----------------|:---------------|
| cgb_10y               |               0 |                  |                |            2958 |            2958 |               2958 | 2015-01-04       | 2026-11-13     |
| cgb_1y                |               0 |                  |                |            2958 |            2958 |               2958 | 2015-01-04       | 2026-11-13     |
| core_cpi_yoy          |               0 |                  |                |             154 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| cpi_mom               |             226 | 2008-01-31       | 2026-10-31     |             380 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| cpi_yoy               |             226 | 2008-01-31       | 2026-10-31     |             521 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| exports_yoy           |             226 | 2008-01-31       | 2026-10-31     |             226 |               0 |                  0 |                  |                |
| gdp_real_yoy          |              83 | 2006-03-31       | 2026-09-30     |             217 |             217 |                 51 | 2014-03-31       | 2026-09-30     |
| gdp_real_ytd_yoy      |               0 |                  |                |             135 |              52 |                 52 | 2013-12-31       | 2026-09-30     |
| imports_yoy           |             226 | 2008-01-31       | 2026-10-31     |             226 |               0 |                  0 |                  |                |
| industrial_va_yoy     |              54 | 2021-11-30       | 2026-09-30     |             256 |             128 |                127 | 2014-03-31       | 2026-09-30     |
| industrial_va_ytd_yoy |               0 |                  |                |             274 |             134 |                134 | 2014-02-28       | 2026-09-30     |
| lpr_1y                |              12 | 2025-11-20       | 2026-10-20     |              99 |               0 |                  0 |                  |                |
| m1_new_yoy            |               0 |                  |                |              42 |              21 |                 21 | 2025-02-28       | 2026-10-31     |
| m1_yoy                |             225 | 2008-01-31       | 2026-09-30     |             336 |             132 |                132 | 2014-01-31       | 2024-12-31     |
| m2_yoy                |             225 | 2008-01-31       | 2026-09-30     |             519 |             153 |                153 | 2014-01-31       | 2026-10-31     |
| new_rmb_loans         |              13 | 2025-08-31       | 2026-09-30     |             277 |             121 |                121 | 2014-01-31       | 2026-01-31     |
| pmi_mfg               |             226 | 2008-01-31       | 2026-10-31     |             522 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| pmi_new_orders        |              60 | 2021-11-30       | 2026-10-31     |             356 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| pmi_nonmfg            |             226 | 2008-01-31       | 2026-10-31     |             383 |             157 |                154 | 2014-01-31       | 2026-10-31     |
| ppi_mom               |              42 | 2021-12-31       | 2026-10-31     |             196 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| ppi_yoy               |             250 | 2006-01-31       | 2026-10-31     |             545 |             154 |                154 | 2014-01-31       | 2026-10-31     |
| retail_sales_yoy      |               0 |                  |                |             258 |             128 |                127 | 2014-03-31       | 2026-09-30     |
| retail_sales_ytd_yoy  |              47 | 2021-11-30       | 2026-09-30     |             285 |             141 |                140 | 2014-02-28       | 2026-09-30     |
| rmb_loans_ytd_flow    |               0 |                  |                |             236 |              71 |                 71 | 2014-03-31       | 2026-10-31     |
| shibor_1w             |            5019 | 2006-10-08       | 2026-11-12     |            8227 |            3208 |               3208 | 2014-01-02       | 2026-11-13     |
| shibor_3m             |            5019 | 2006-10-08       | 2026-11-12     |            8227 |            3208 |               3208 | 2014-01-02       | 2026-11-13     |
| shibor_on             |               0 |                  |                |            3208 |            3208 |               3208 | 2014-01-02       | 2026-11-13     |
| tsf_month_flow        |               0 |                  |                |             250 |             109 |                109 | 2015-01-31       | 2026-01-31     |
| tsf_stock             |               0 |                  |                |             266 |             133 |                133 | 2014-12-31       | 2026-10-31     |
| tsf_stock_yoy         |              12 | 2025-09-30       | 2026-09-30     |             145 |             133 |                133 | 2014-12-31       | 2026-10-31     |
| tsf_ytd_flow          |               0 |                  |                |             216 |              75 |                 75 | 2015-03-31       | 2026-10-31     |
| usdcny_fixing         |               0 |                  |                |            3128 |            3128 |               3128 | 2014-01-02       | 2026-11-13     |

逐序列实际缺口和准入状态见 macro_coverage；语义修复、源公告和交叉核对见 macro_reconciliation；日期与修订限制见 macro_pit_validation。不能将原覆盖长短当作原数值可信证明。

## 3. 联合研究数据集

| feature_set                    | status   | sample_version          |   features |   initial_candidate_weeks |   2020_train |   2020_validation |   2021_train |   2021_validation |   2022_train |   2022_validation |
|:-------------------------------|:---------|:------------------------|-----------:|--------------------------:|-------------:|------------------:|-------------:|------------------:|-------------:|------------------:|
| M                              | eligible | main_v1                 |         25 |                       nan |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_core                  | eligible | common_core_v1          |         57 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_prices                | eligible | common_prices_v1        |         45 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_growth                | eligible | common_growth_v1        |         61 |                       148 |          144 |                32 |          180 |                36 |          221 |                29 |
| M_plus_Z_credit                | eligible | common_credit_v1        |         57 |                        96 |           94 |                21 |          117 |                22 |          141 |                14 |
| M_plus_Z_rates_fx              | eligible | common_rates_fx_v1      |         61 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_external              | blocked  | common_external_v1      |         25 |                         0 |          nan |               nan |          nan |               nan |          nan |               nan |
| M_plus_Z_full_eligible         | eligible | common_full_eligible_v1 |        149 |                        96 |           94 |                21 |          117 |                21 |          140 |                14 |
| M_plus_Z_core_without_prices   | eligible | common_core_v1          |         49 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_core_without_growth   | eligible | common_core_v1          |         49 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_core_without_credit   | eligible | common_core_v1          |         53 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |
| M_plus_Z_core_without_rates_fx | eligible | common_core_v1          |         45 |                       168 |          164 |                32 |          200 |                38 |          243 |                29 |

核心保留 450 个市场有效周，开发期真正 OOF 为 99 周，M 和 M+Z 样本/标签/折完全配对。各组 manifest 和逐宏观可得性明细保存排除理由。

## 4. 预测框架

四类模型共享 Dataset Loader、训练内预处理、标签成熟约束、年度扩展内外层折、固定搜索预算、模型保存/加载、概率/事件/配对评价。特征注册表可切换经济组、完整组与核心组消融。参见 docs/experiment_framework.md。

## 5. 真实开发期 Benchmark

| algorithm         | feature_set   |   n |    brier |   log_loss |   detected_events |   eligible_events |   lead_mean |
|:------------------|:--------------|----:|---------:|-----------:|------------------:|------------------:|------------:|
| gradient_boosting | M             |  99 | 0.245265 |   0.706305 |                 3 |                 9 |     8.33333 |
| gradient_boosting | M_plus_Z_core |  99 | 0.235545 |   0.70806  |                 4 |                 9 |     8       |
| historical_rate   | M             |  99 | 0.2246   |   0.644083 |                 0 |                 9 |   nan       |
| historical_rate   | M_plus_Z_core |  99 | 0.2246   |   0.644083 |                 0 |                 9 |   nan       |
| logistic          | M             |  99 | 0.254465 |   0.707498 |                 3 |                 9 |     4.66667 |
| logistic          | M_plus_Z_core |  99 | 0.242176 |   0.71997  |                 2 |                 9 |    12       |
| random_forest     | M             |  99 | 0.283921 |   0.786075 |                 2 |                 9 |     4.5     |
| random_forest     | M_plus_Z_core |  99 | 0.2954   |   0.850488 |                 1 |                 9 |     4       |

核心 Brier 配对增益（M 减 M+Z）：

| algorithm         |        mean |      lower |     upper |   block_weeks |   repetitions | method                      |
|:------------------|------------:|-----------:|----------:|--------------:|--------------:|:----------------------------|
| gradient_boosting |  0.00971998 | -0.0281453 | 0.055114  |             8 |           500 | moving_calendar_week_blocks |
| historical_rate   |  0          |  0         | 0         |             8 |           500 | moving_calendar_week_blocks |
| logistic          |  0.012289   | -0.0457989 | 0.0811165 |             8 |           500 | moving_calendar_week_blocks |
| random_forest     | -0.0114792  | -0.0424978 | 0.0278641 |             8 |           500 | moving_calendar_week_blocks |

事件阈值按每年最多两个误报周在开发期选择，因此开发预警命中偏乐观。区间小样本且未校正多重比较；不据此宣称最终期增量价值。完整各组结果、校准、可靠性和事件明细见 reports/benchmark 与 experiments/metrics。

## 6. 自动测试与复现

tests=56, failures=0, errors=0, skipped=0。重跑状态：`{'run_id': 'dev-e47c442b6de1233e', 'offline_data_rebuild': 'exact SHA256 match', 'checked_artifacts': 22, 'model_replay': 'PASS: exact prediction and metric SHA256; all model/calibrator bytes identical', 'prediction_hash_before': '710c6f056af41d6f14f06cd19866389d701144e90f833fd03aca148d629c390d', 'metrics_hash_before': 'f25478e3974357c3551e591e13e3505a021cc3d744fee9a1f80b96ce2ed9a781', 'model_artifacts_checked': 408, 'model_hash_manifest': 'audit/framework/model_replay_hashes.json'}`。原市场核心由冻结日度数据重建到观测、状态、事件、周度特征、目标与折并比较；未宣称外部原始全量采集已重跑。运行命令及依赖见 docs/reproducibility.md。

## 7. 研究限制与后续

主核心可开展受限定数据版本下的开发配对研究，不能标成所有变量严格 PIT。进出口历史版本未认证、DR007 无可靠长历史、LPR/M1 新定义历史短，不能强行进入主组。最终期需冻结主模型、宏观组、校准、阈值和稳健性方案后单独评价；当前保留隔离。详见 docs/research_limitations.md。未提交或推送 Git。

补充外测准备事项：完整历史核查另发现 2025-01 M2 的原公告未在当前目录定位；不影响开发期 99 周的配对结果，但该月尚未认证。实际可得信息沿用前期已公布值，未用未来修订值回填。详见 macro_coverage 的全历史范围补充验收及 audit/framework/macro_full_history_gaps.csv。
