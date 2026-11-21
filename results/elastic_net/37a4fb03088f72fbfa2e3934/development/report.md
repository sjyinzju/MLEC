# Elastic Net 市场状态预测复算

运行 `37a4fb03088f72fbfa2e3934` · 阶段 `development` · 套件 `full`

## 运行和数值验收

零系数候选仅在训练频率截距、完整 KKT 和原惩罚目标同时成立时采用解析解。
旧求解器在全部斜率为零时可能首轮退出，随机更新后的截距仍有一阶残差。
七项回归沿用增广 Lasso/LARS 和独立对偶间隙。纯 L1 路径出现已复现的内部形状错误时，记录原异常并调用现有对偶 QP。收紧停止条件的续解告警仍保存。

选定逻辑月任务 9,936。阶段物理任务 15,384，其中通过 15,384，失败 0。
记录到的估计器拟合调用 46,375，零迭代解析解 775。
最大片内进程峰值内存 0.29 GiB。各进程峰值可能出现于不同时刻。

## 主比较

正值表示 M＋Z 降低损失。区间使用 8 周同步日历区块和 2,000 次重采样。4 周、12 周及逐年结果见明细。单侧 p 值检验正向增益，负向改善区间按其本身方向解读。非线性模型主检验尚未齐备，Holm 校正值留空。

- 000852.SH classification，M 0.43673，M＋Z 0.4488，增益 -0.012068，95% 区间 [-0.052992, 0.028822]，150 周。
- 000985.SH regression，M 0.47184，M＋Z 0.47164，增益 0.0002048，95% 区间 [-1.6383e-06, 0.00036614]，150 周。
- 000300.SH classification，M 0.18226，M＋Z 0.20003，增益 -0.017772，95% 区间 [-0.09935, 0.037935]，150 周。
- 000905.SH classification，M 0.18324，M＋Z 0.19934，增益 -0.0161，95% 区间 [-0.068473, 0.033503]，150 周。
- 000985.SH classification，M 0.17034，M＋Z 0.21495，增益 -0.044613，95% 区间 [-0.14077, 0.021137]，150 周。
- 000852.SH regression，M 0.46166，M＋Z 0.46166，增益 0，95% 区间 [0, 0]，150 周。
- 000905.SH regression，M 0.43382，M＋Z 0.48085，增益 -0.047033，95% 区间 [-0.099859, -0.004511]，150 周。
- 000300.SH regression，M 0.387，M＋Z 0.42873，增益 -0.041737，95% 区间 [-0.088931, -0.0051062]，150 周。

### 金融特征与朴素基准

- 000300.SH，M 相对平滑训练频率基准的 Log Loss 降幅 0.023959，相对历史 20 日持续基准的五维平方误差降幅 31.66%。
- 000852.SH，M 相对平滑训练频率基准的 Log Loss 降幅 0.040562，相对历史 20 日持续基准的五维平方误差降幅 25.52%。
- 000905.SH，M 相对平滑训练频率基准的 Log Loss 降幅 0.088221，相对历史 20 日持续基准的五维平方误差降幅 26.43%。
- 000985.SH，M 相对平滑训练频率基准的 Log Loss 降幅 0.051619，相对历史 20 日持续基准的五维平方误差降幅 31.62%。

## 预警和解释

字典风险映射为 `{"risk_downside": [0], "risk_liquidity": [1], "risk_broad_decline": [0]}`。同一状态映射产生相同的类别概率信号。低换手仅描述交易活跃度，流动性判断同时参考 Amihud 价格冲击。
连续风险辅助结果对七项原指标分别使用初始训练期不利方向的 90% 分位。报警阈值仅在开发期按固定负担选取。重叠窗口簇只表示窗口合并后的事件段，统计推断使用区块 Bootstrap。
状态 0 的平均精确率、ROC-AUC、校准、逐类召回、无支持提示和各负担检出率见下列明细。

- [分类和朴素基准](tables/core_classification.csv) · [分类支持与排序](tables/class_precision_recall.csv) · [校准](tables/reliability.csv)
- [七目标和五维回归](tables/core_regression.csv) · [预警](tables/warning_value.csv) · [类别支持](tables/class_support.csv)
- [逐周损失和贡献](tables/weekly_loss_diagnostics.csv) · [年度分位数](tables/weekly_loss_quantiles.csv) · [删极端周敏感性](tables/extreme_week_sensitivity.csv)
- [固定参数比较](tables/fixed_parameter_sensitivity.csv) · [宏观分组](tables/macro_groups.csv) · [宏观发布时间审计](tables/macro_lineage_audit.csv)
- [运行质量](tables/runtime_quality.csv) · [覆盖](tables/coverage_status.csv) · [候选有效率](tables/candidate_status.csv)

## 研究范围

本阶段包含全部 96 个原定固定 M＋Z 参数配置。
同参比较使用 M 和 M＋Z 各自的开发获胜参数进行交叉对照。分组、同参和极端周分析为辅助探索。
宏观特征按可得日、口径和来源类型审计。历史重建视图包含代理可得时间，无法证明当年的真实实时数据版本。
信息年龄、发布时钟和金融模块的独立特征投影仍需单独的数据视图。
2023 年之后的测试时代此前已被查看，本运行属于实现修复后的复算。

## 来源身份

- runtime_version `experiment-runtime-v2`
- contract_version `model-io-v1`
- data_version `5d57508f09249cf50b1a2e52`
- feature_version `6d50d9efbc48040f0912`
- target_version `f49e499c375fa557fcb0`
- dictionary_version `76bf6837dc5e32262c99`
- original_seal_hash `728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f`
- interface_code_hash `26d9fc0824f8f702707c0a17c3a1d68bef27d49089b59d767668252ece68ac12`
- experiment_code_hash `ad0d0fa29e71df85045853c0851fc5af25fab85a511ab90b5a760bfccf07f7ef`
- protocol_hash `a7d5fb1771ac0724bce7183c5ec447f41d6c9763c26b784336eda64e6d3da9d7`
- experiment_plan_hash `e26b6c73b5002537aba279f149db99df63a8e4cbee85a967bddc9495a97ca47a`
- config_hash `b948de46612a99373932c3da38e3234e0790902e1ac61bda0b41ce73437d31b1`
