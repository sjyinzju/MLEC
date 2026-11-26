# 60 个交易日 RBF-SVM 独立重训

登记为 `rbf-60td-independent-20261126-v1`。沿用 2026 年 11 月 13 日封版的日历、股票和宏观源数据。从同一个数据接口读取四市场，分别比较市场信息 M 和市场加宏观信息 M+Z。每个市场完成三状态分类和五维七项回归。

## 60 日历史输入与目标

- 过去 15、60、180 个交易日的量价、风险、流动性和市场结构全部从日线与当时成分重新测量。当前状态和其他市场同期状态采用过去 60 日，状态滞后采用 3、6、12 周。
- 用当时可得的封版事实与修复记录重建三种宏观视图。日度序列生成过去 15、60 个有效观测的变化与波动。正式宏观序列另计算 `t` 与 `t-60` 个交易日各自可得的发布值之差。同一统计口径和累计量同年度约束按序列检查。发布水平、发布时间和适用性等变量由原始记录按时点生成。
- 未来窗口从预测锚点后第 1 个交易日到第 60 个交易日。以 2019 年底已成熟的同日期等市场权重样本拟合三状态字典。独立比较四种协方差形式，沿用 BIC、前推似然与分块稳定性联合排名。过去 60 日的当前状态使用同一字典。
- 生成独立数据版本和封版，核验两个宏观锚点各自的可得时点及过去窗口的末日。样本标识、训练成熟度、市场配对、固定初始回归评价尺度仍由公共契约处理。

## 独立选参与样本外复核

新候选登记在 `config/experiments/rbf_60d_retuned_20261126.json`。M 和 M+Z 每个市场、任务分别搜索 8 和 24 个配置。搜索覆盖各候选相同的全部成熟开发评分月。分类比较核尺度、C、类别权重和 softmax 温度。初始时间留出仍缺下跌类，概率使用开发段选定温度的固定映射。七个 SVR 对每个核布局分别选 C 和 epsilon，再按五维等权选取布局。

开发段锁定每个市场/任务/信息集的获胜参数，另锁定每个 M+Z 比较的最佳正宏观权重。测试段分别评价独立选参的 M 对 M+Z，以及固定正权重方案求解参数时移入宏观块的配对。进入测试前校验开发证据与锁文件。预测覆盖 47 个测试月，评分取已成熟的周，使用同步 16 周移动区块区间和 12、20 周敏感性。测试期为历史复核。

## 复现

在仓库根目录使用固定研究环境，`STOCK_CACHE` 指向原快照 2014–2026 年的股票日收益缓存目录。

```text
python -m scripts.market_state.run build-60d --rebuild-inputs --stock-cache STOCK_CACHE --output results/rbf_60d_retuned_20261126/data
python -m scripts.market_state.run interface-preflight --data-root results/rbf_60d_retuned_20261126/data --receipt-dir results/rbf_60d_retuned_20261126/interface
python -m pytest
python -m scripts.market_state.experiments.rbf_60d run --execute --data-root results/rbf_60d_retuned_20261126/data --interface results/rbf_60d_retuned_20261126/interface --output results/rbf_60d_retuned_20261126/run
```

中断后加 `--resume` 复用同一数据、同一方案的已校验月度任务。报告和逐项评分见 `report.md`、`metrics.csv` 和 `paired_intervals.csv`，开发候选的完整评分与测试前锁定参数见 `development/search` 和 `selection.lock.json`。
