# RBF-SVM 的 60 日和 Z 单独预测实验

两项实验覆盖全 A、沪深 300、中证 500 和中证 1000。各市场按月扩展训练，并在周末锚点预测三种未来状态及五个经济维度的七个连续结果。训练时只读月初拟合截止前已成熟的标签。20 日 Z 结果与原实验的 M 和 M+Z 在相同评分周上配对。

## 60 个交易日

`build-60d` 从 2026 年 11 月 13 日的封版输入构建派生数据。收益以锚点收盘价为基准，流动性、广度和相关性等使用锚点之后第 1 至第 60 个交易日。原历史输入特征及其 20 日当前状态词典沿用原数据。构建时先用同一套输入复算原 20 日窗口，对比逐周目标值、窗口日期和有效性。

未来状态词典沿用三成分 tied-covariance GMM 的结构，在 2019 年底前成熟的 60 日标签上重新拟合，各市场使用相同日期。60 日下跌状态多集中于 2015 年。原时间留出块缺少满足三类支持要求的校准样本，60 日分类统一使用固定 softmax 映射 RBF-SVC 的 OVR 分数。`h60/calibration_support.json` 记录初始月和开发末月的留出支持情况。M 和 M+Z 使用同一组锁定的 SVC 核与正则化参数和七个 SVR 参数。回归评分使用各市场 60 日初始训练样本的固定尺度。

## 20 个交易日，仅 Z

Z 是原 M+Z 主数据视图的宏观投影，使用相同的发布时间、缺失处理、历史训练周、目标和评分周。既有分组核指数为 `eta * (d_M² + lambda * d_Z²)`，单块核使用 `eta_Z = eta * lambda`。每个市场和任务沿用上一轮开发期正宏观权重获胜方案的特征表示、正则化、校准规则和回归目标参数，每月重新拟合权重。对照包括旧实验分别调参的 `retuned_core` 和共用求解参数的 `fixed_full_params`。

## 复现和评分

以下命令从仓库根目录运行，`STOCK_CACHE` 指向原快照 2014–2026 年的股票日收益 Parquet 分区，`PREVIOUS_RUN` 指向已完成的原 RBF-SVM 实验目录。

```text
python -m scripts.market_state.run build-60d --stock-cache STOCK_CACHE --output results/rbf_followups_20261125/data60
python -m scripts.market_state.run interface-preflight --receipt-dir results/rbf_followups_20261125/interface20 --information-set M --information-set M+Z --information-set Z
python -m scripts.market_state.run interface-preflight --data-root results/rbf_followups_20261125/data60 --receipt-dir results/rbf_followups_20261125/interface60
python -m pytest
python -m scripts.market_state.experiments.rbf_followups run --execute --data60 results/rbf_followups_20261125/data60 --interface20 results/rbf_followups_20261125/interface20 --interface60 results/rbf_followups_20261125/interface60 --previous-run PREVIOUS_RUN --output results/rbf_followups_20261125/run
```

中断后可在输入、代码和参数身份相同的情况下加 `--resume` 复用已经校验的月度产物。`report.md` 提供样本外的配对损失，`metrics.csv` 包含七个原单位回归指标、分类指标和真实状态数，`paired_intervals.csv` 包含两个实验各自的 2,000 次同步移动区块 bootstrap 和区块长度敏感性。60 日与 20 日使用不同的目标和回归尺度，跨预测期限的原始损失没有共用读数口径。区间是探索性配对诊断，20 日测试样本已在上一轮使用过。
