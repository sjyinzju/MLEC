# 给宏观侧与后续实证研究的交接

已交付完整市场侧真实数据，没有等待宏观数据；没有预测概率、模型效果、调参或策略结果。源目录只读。主口径000300.SH价格指数；阈值版本`thr-bc957a16047c6fd2`，协议`market-research-v2.0.0`。

## 读取接口

- 默认输入：`data/research_v2/market_features_weekly.parquet`，严格按`config/research_v2/feature_whitelist.json`选列；state_id是类别。估值单独可选。
- 股票代理扩展输入：`market_features_weekly_with_proxies.parquet`，代理默认不进入主输入组；有覆盖、股票数和缺失标记。
- 目标：`prediction_targets_weekly.parquet`是长表，键`sample_id+horizon`；主H20使用`risk_set & target_valid`及`y_new_episode_next20`。未来路径观测单独在`future_outcomes_weekly.parquet`。
- 事件：`risk_episodes.parquet`；连接：`sample_to_event.parquet`。未来ID、onset、exit、最终持续期与严重度只用于标签/评价。
- 折：`fold_membership.parquet`，计划`audit/research_v2/fold_manifest.parquet`。`eligible_for_fit`必须true；模型只能用成熟目标。
- 字段字典：`audit/research_v2/field_dictionary.csv`，含中文、公式、单位、来源、窗口、可得时点、缺失含义、角色与版本。

| H | 保留周数 | 未来路径完整周 | 主风险集周 | 有效新事件目标周 | 有效时点首日 | 有效时点末日 | 最后标签结束日 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 599 | 595 | 454 | 450 | 2015-04-10 | 2026-08-21 | 2026-09-18 |
| 5 | 599 | 598 | 454 | 453 | 2015-04-10 | 2026-09-11 | 2026-09-18 |
| 40 | 599 | 591 | 454 | 447 | 2015-04-10 | 2026-07-10 | 2026-09-04 |

候选周范围2015-01-09—2026-09-18，共599；有效60日主输入周586。60日历史+20日未来的窗口候选仍为582，进一步风险集后主目标有效450周。排除详情在`sample_exclusions.parquet`，尾部未来不足保持NA；辅助40日期限不影响主样本。

## 宏观as-of合并

`sample_id`固定为CSI300-YYYYMMDD，`asof_time`为该完整周最后SSE交易日18:00（Asia/Shanghai）。每条宏观事实必须带真实公布/修订可得时间：只合并`macro_research_available_at<=asof_time`的最近已公布版本，不以统计期末日期代替公告时间。只有日期没有小时的宏观公告，需双方预先约定保守可得规则，记录依据；不能假定同日18:00前一定公布。

`source_available_at`、原库`_available_at`可能是2026年采集/入库，不能用于伪造早年公开时间。市场`research_available_at`基于收盘重建假设，dailybasic滞后1日；这与宏观真实公告时刻不是同一种证据。

M和M+Z须共享sample_id、目标、风险集、折及共同样本版本。宏观覆盖不足时双方联合确定共同日期和排除原因，再生成一个共同样本掩码；不能各自dropna后直接比较。宏观修订、混频聚合、发布时间、覆盖尚待联合验收，不影响本轮市场侧交付完成。

## 后续训练与评价约束

开发2020/2021/2022向前扩展；每折fit_cutoff前标签必须已按完整H成熟。2022末未成熟目标在2022末选择中boundary_purged，之后可进入更晚训练计划。最终2023起按月预设更新计划，允许使用更早已成熟历史，但不能用测试反馈改变阈值/模型定义。无初始2015—2019内部实时回测。

后续标准化、填补、特征选择、重采样仅训练折拟合；测试特征可读取此前历史。输入白名单禁止所有数值列自动入模。预测配对schema为`paired_prediction_schema.json`，当前只有schema，无虚假概率。

事件归属按onset_date所在评价期；每事件一次检出，优先最早有效报警；报警必须在onset前、H窗口内、对应风险集。`lead_to_trigger`是交易日到阈值触发的距离，不是提前于股灾开始。`current_drawdown_at_prediction`保留报警时已发生损失；不能把未来事件尚未发生的损失伪填为0。跨边界与完整H先行窗口、周机会字段均保留。

五维状态：

| 维度 | 状态 | 限制 |
| --- | --- | --- |
| 趋势 | FORMAL | price index, no dividends; no bull/bear assignment |
| 波动 | FORMAL | daily close-based annualized proxy, not high-frequency RV |
| 下行损失 | FORMAL | observed window price losses only |
| 活跃度及流动性 | FORMAL_ACTIVITY_AND_PROXY_LIQUIDITY | activity is not liquidity crisis; observed stock proxy not exact full-market illiquidity |
| 市场结构 | PROXY | BLOCKED for exact CSI300/full historical market universe; dated master includes delisted but observed-revision and code-history gaps remain |

`feature_start`表示最长固定60日窗口起点；递归状态另有`state_history_start`保存历史递推起点。`reference_period_realtime_eligible`明确标出参考期不能当作实时测度评价。相关结构使用同一日期完整股票窗，但不同窗口股票组成可变，其变化也可能影响均值，因此必须连同股票数/覆盖率解释。

股票证据：5554只master范围内沪深股票，333只退市保留；4265条行情来自master中无记录的旧/异常代码，具体为`000043.SZ/000022.SZ/300114.SZ`；282674条重建上市池缺行情中271480有同日S停牌记录，11194未解释。248条可用映射仅BSE，精确沪深历史代码池仍BLOCKED；观测代理可用，不称沪深300精确成分广度。

联合验收需确认：共同宏观样本、真实公告与修订as-of规则、可选代理是否进入扩展M、模型训练折预处理和事件去重评价实现。代码正确、测度有依据、样本是否充足、宏观是否有效是四个不同结论；本轮只完成前两项的可复核材料与样本数量证据，宏观有效性未验证。
