# 联合样本验收

冻结周度候选 599；市场有效风险周 450；核心宏观共同周 450。这里包括未用于模型选择的 2023+ 候选结构；其新建标签列已隐藏。真正外层开发 OOF 受原时间折、标签成熟/边界 purge 约束，数量如下。

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

核心组保留全部 99 个市场开发 OOF 周。增长/信用/full 组因历史公告覆盖、春节合并、陈旧上限而样本更短，均在相同版本重新训练 M；不得跨样本版本直接相减指标。每个样本的 risk_set、target_valid、included_market/core、macro_complete 和 joint_exclusion_reason 在对应共同样本表中；每条宏观缺失/陈旧原因在 macro_availability。初始候选计数并非每折可用训练计数，差额来自原标签成熟度边界。

as-of 防泄漏测试覆盖延迟发布、旧期修订、未来扰动、历史截断；所有派生记录保留使用的 source_record_ids，可得时间取所用版本时间最大值。日频窗口基于 SSE 开放日，缺少报价的窗口不补值。标准化、缺失填充、方差过滤和类别编码仅在训练折拟合。原数据/标签/协议哈希另验收。
