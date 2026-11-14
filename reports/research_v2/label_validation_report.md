# 市场标签验证报告

主阈值：qV=28.8522%年化波动，qD=7.6578%窗口最大回撤；参考期2015-02-02—2019-12-31，1199日，线性分位数。以下只展示初始参考/开发期资料；2023以后诊断在heldout单独保存，不用来选标签。

## 状态与事件

| 时期 | 有效状态日 | S0/S1/S2/S3计数 | 已确认新组合事件 | 事件观测持续期中位数 | 最大观测持续期 | 右删失事件 | 事件中恢复日 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reference | 1199 | {'S0': 880, 'S3': 161, 'S2': 79, 'S1': 79} | 13 | 22.0 | 115 | 0 | 62 |
| development | 728 | {'S0': 556, 'S3': 73, 'S2': 72, 'S1': 27} | 9 | 25.0 | 32 | 0 | 41 |

完整状态占比、转换矩阵、单压力日事件、压力日数与恢复日数在`audit/research_v2/reference_development_statistics.json`。持续期在各期末截断计算，右删失不冒充最终已知持续期。S1和S2不可按编号当严重度。

## 非构造指标诊断

| 时期 | 类别 | 下行半波动均值 | 最差单日收益均值 | 期末回撤均值 | 观测股票下跌比例均值 |
| --- | --- | --- | --- | --- | --- |
| reference | S0 | 0.0945793 | -0.0180716 | 0.0189543 | 0.484514 |
| reference | S1 | 0.205379 | -0.0441836 | 0.018954 | 0.372292 |
| reference | S2 | 0.183121 | -0.0310086 | 0.0724887 | 0.438316 |
| reference | S3 | 0.386657 | -0.0704096 | 0.117973 | 0.488708 |
| development | S0 | 0.108519 | -0.0191179 | 0.0223468 | 0.498367 |
| development | S1 | 0.232474 | -0.0467269 | 0.0380024 | 0.552978 |
| development | S2 | 0.193915 | -0.0333508 | 0.0626292 | 0.476562 |
| development | S3 | 0.278882 | -0.0526781 | 0.0861627 | 0.455927 |

这些仅作经济解释和边界检查；下行半波动、最差单日损失与期末回撤依然与价格压力相关，不能当独立因果证明。广度来自已排除停牌/缺因子的观测股票样本，认证状态PROXY。没有仅凭构造指标组间差异宣称标签科学。

## 样本数量链

| 时期 | 候选周 | 市场特征完整周 | 主风险集周 | 完整标签周 | 阳性周 | 样本覆盖去重事件 | 期内具预警机会事件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reference | 255 | 242 | 168 | 168 | 42 | 14 | 13 |
| development | 154 | 154 | 112 | 112 | 32 | 9 | 9 |

这些数量回答不同问题。风险集仅包含已确认非事件状态；恢复期样本仍保留且主标签NA。样本覆盖去重事件可能含跨年未来起点，期内事件按onset归属，不能把两列机械看成同一分母。具有机会要求完整H日前史且至少一个有效周风险集点；这是冻结测度下的历史回放机会，不声称2015年已有实际预测系统。

当期截止时可真正用于拟合/选择的成熟口径另列：

| 时期 | 当期末已成熟目标 | 其中阳性周 | 成熟样本覆盖去重事件 | 跨边界未成熟周 |
| --- | --- | --- | --- | --- |
| reference | 164 | 41 | 13 | 4 |
| development | 108 | 32 | 9 | 4 |

上面的完整标签周表示用当前本地全样本后来可计算，不能用于冒充当期末已经知道。初始参考期资料选择只用初始期状态/事件和截至2019末成熟目标；开发年边界另外按逐折manifest隔离。固定阈值的历史训练标签有`measurement_standard_available_at=2019-12-31 18:00`，所有训练折还核对已越过该测度校准时刻；参考期没有被宣称实时评价。

## 预设单因素敏感性

| 方案 | 时期 | 状态一致率 | 新组合事件 | 相对主事件变化 | 匹配起点偏移中位数/交易日 | 单压力日碎片 | 有效目标 | 阳性目标 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| q75 | reference | 0.9116 | 12 | -1 | 0.0 | 0 | 154 | 37 |
| q75 | development | 0.8997 | 10 | 1 | 0.0 | 0 | 106 | 35 |
| q85 | reference | 0.9049 | 9 | -4 | 4.0 | 0 | 185 | 38 |
| q85 | development | 0.8874 | 9 | 0 | 0.0 | 0 | 120 | 29 |
| exit3 | reference | 1.0000 | 13 | 0 | 0.0 | 0 | 174 | 45 |
| exit3 | development | 1.0000 | 10 | 1 | 0.0 | 0 | 114 | 32 |
| exit10 | reference | 1.0000 | 12 | -1 | 0.0 | 0 | 153 | 33 |
| exit10 | development | 1.0000 | 7 | -2 | 0.0 | 0 | 102 | 30 |
| terminal_drawdown | reference | 0.9116 | 19 | 6 | 0.0 | 1 | 152 | 54 |
| terminal_drawdown | development | 0.8750 | 14 | 5 | -1.0 | 1 | 103 | 38 |
| h5 | reference | 1.0000 | 13 | 0 | 0.0 | 0 | 168 | 14 |
| h5 | development | 1.0000 | 9 | 0 | 0.0 | 0 | 112 | 10 |
| h40 | reference | 1.0000 | 13 | 0 | 0.0 | 0 | 168 | 57 |
| h40 | development | 1.0000 | 9 | 0 | 0.0 | 0 | 112 | 55 |

起点偏移按20交易日内最近起点一对一贪心匹配；未匹配计数和类别稀疏明细在JSON。H5/H40只改事件搜索期限，状态一致率应为1；未因辅助40日期限统一截短20日样本。敏感性没有模型、择优或排名；测试期明细仅在`heldout/sensitivity_details.json`。

## 实际执行的检查

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| formula_and_event_unit_tests | PASS | {'tests': 23} |
| full_real_observations_recomputed | PASS | {'rows': 2850} |
| real_history_truncation_invariance | PASS | {'cutoff': '2020-06-30', 'rows': 1336, 'includes_stock_proxy_reselection': True} |
| real_history_truncation_invariance | PASS | {'cutoff': '2022-12-30', 'rows': 1947, 'includes_stock_proxy_reselection': True} |
| real_history_truncation_invariance | PASS | {'cutoff': '2024-06-28', 'rows': 2306, 'includes_stock_proxy_reselection': True} |
| future_price_perturbation_and_reference_threshold_invariance | PASS | {'cutoff': '2022-06-30'} |
| all_horizon_maturity_risk_sets_and_all_fold_boundaries | PASS | {'folds': 48, 'fit_memberships': 50706, 'boundary_purged_memberships': 628} |
| feature_input_whitelist_and_physical_target_separation | PASS | {'default_features': 25} |
| proxy_availability_and_same_market_sample_ids | PASS | {'rows': 599} |
| independent_raw_stock_year_boundary_return_and_CNY_units | PASS | {'cases': 36} |
| complete_real_core_pipeline_semantic_reproduction | PASS | {'weekly_rows': 599, 'target_rows': 1797, 'candidate_60past_20future': 582} |

人工路径测试日志与JUnit为`audit/research_v2/logs/unit_tests.log`、`unit_tests.xml`。真实截断在2020-06-30、2022-12-30、2024-06-28重算全部此前主输入/实时状态/事件起点，并重新读取历史股票返回检查代理；未来扰动在2022-06-30后进行，初始阈值、此前输入与事件不变。未要求尚未成熟标签或事后结束信息提前一致。逐折训练成熟度、验证年边界、输入白名单已执行断言。

结论仅限代码与数据规则通过这些检查。事件量有限、每周目标重叠且多个阳性周可能指同一事件，后续概率评价须同时报告事件级结果和不确定性；本轮未为凑事件改参数，未训练预测器，未检验宏观增量有效性。
