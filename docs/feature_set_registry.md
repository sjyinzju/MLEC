# 特征组注册表

实际机器可读定义：`config/experiments/feature_sets.json`。注册由 `build-dataset` 生成，不依赖模型表现。

| 组 | 经济范围 |
|---|---|
| M | 冻结市场特征白名单 |
| M_plus_Z_core | CPI、PPI、制造业 PMI、新订单、M2、Shibor 1W/3M |
| M_plus_Z_growth | PMI、工业、零售、GDP；累计与当期分开 |
| M_plus_Z_prices | CPI/PPI 同比与环比、核心 CPI |
| M_plus_Z_credit | 货币、贷款、社融；流量、存量分别命名 |
| M_plus_Z_rates_fx | 利率与汇率金融价格信息 |
| M_plus_Z_external | 进出口，历史公告版本未验收则 blocked |
| M_plus_Z_full_eligible | 当前通过时间/历史覆盖筛选的全部指标，探索性高维组 |
| M_plus_Z_core_without_* | 预先定义的按经济组删去核心变量的消融 |

核心七项必须全部存在。扩展组只包含初始期至少 40 个可观察周的指标，注册表列出实际组成；这不是基于预测表现选变量。共同样本需有至少 40 个初始有效风险周，且三个开发年份均有样本。后续切换组时必须使用其注册的 `sample_version`，并在这个版本上重新训练 M。

共同样本要求所有该组原始 latest 值存在且未陈旧。月度上限 75 天、季度 150 天、日度 10 天（相对统计期间末）；工业与零售春节合并发布导致的缺失不伪造。previous/change/窗口均值的剩余缺失由每个训练折的中位数处理；常数列过滤、标准化、类别编码都在训练折拟合。每组的数量、共同样本和排除原因见联合质量报告。

短历史或未认证指标仍留候选池，不能为了进入 full 组扩大可得性假设。LPR 当前机制从 2019-08 开始，M1 新定义从 2025-01 开始。DR007 不用 R007 或 FDR007 替代。

核心 leave-one-group-out 共用 `common_core_v1`，保持完整核心的样本资格，已在默认开发配置中实际运行。相对完整核心的组删除损失差在 `reports/benchmark/core_ablations.md`。
