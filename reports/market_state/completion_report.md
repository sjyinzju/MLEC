# 新版研究 A—C 集中执行报告

唯一内容依据：[market-state-research-v3.0](../../docs/MLEC_research_protocol.md)。真实处理区间：2014-01-02—2026-11-13；候选预测周：2015-01-09—2026-11-13。本轮未运行监督预测模型或 Benchmark，未生成预测成绩或宏观增益结论。

## 执行结果与完成边界

已真实完成四市场完整区间的统一前后向测度、七项连续标签、训练期共享 GMM、当前状态、市场/宏观输入、共同样本和月度时间折。候选周不依赖事件状态或类别置信度。末端未成熟窗口保留空标签。数据与标签研究接口已切换到新版。

**A—C 的处理和标签产物已执行交付；尚不能宣布所有数据要求和目录清理无缺口完成。** 下述字段缺口、证券资料的历史重建精度、旧 Word 文件占用需保留为交付限制；没有以测试通过替代覆盖核查。

## 删除、保留和重构

删除旧事件标签实现、阈值/白名单/敏感性配置、旧折和样本视图、旧预测与模型、重复协议说明及已有版本历史的 archive 副本；逐文件清单见 [cleanup_manifest.json](cleanup_manifest.json)。提取共享 IO/hash 至 `scripts/common.py`，保留采集、标准化、身份、复权、公司行为、修复证据、宏观口径及来源库。保留用户未追踪的协议和 Word 文件。一个已追踪旧 Word 文件因 Windows 进程占用未删除，没有关闭用户应用。

唯一研究命令入口为 `python -m scripts.market_state.run`；读取入口为 `scripts.market_state.framework.load_dataset`；全部研究产物位于 `data/market_state/`。旧来源目录仅作标准化库，不再提供第二套研究样本入口。

## 数据补齐与来源

四指数通过项目已有 Tushare 只读适配器补齐至实际末端；中证全指供应商标识为 `000985.CSI`，显式映射至研究 `000985.SH`。补充 2014 年成员快照和 2026 年后续快照、2026-09-23 后股票行情/股本/复权/停复牌资料，以及最新上市/退市目录。旧日历还缺 2026 年 11 月的开放日期，已重新取得 SSE 日历；当前 3127 个实际开放日期与指数日期逐日相符，20 日边界使用独立交易所日历。请求、取回时间、来源字段见 `data/market_state/source_requests.json`、`calendar_request.json` 和 `sources/`。

北交所行情、复权、股本和代码映射优先从 E:/QuantData 只读 DuckDB 投影，未复制全库或写入外部来源；全 A 横截面从 2021-11-15 加入北交所（此前精选层行情不冒充上市 A 股）。六只试点和其余存量代码分别按 2025-05-06、2025-10-09 生效；来源为[北交所通知](https://www.bse.cn/important_news/200025487.html)及[北京市政府发布](https://www.beijing.gov.cn/ywdt/gzdt/202510/t20251010_4218545.html)。复用沪深修复后的 `*_observations`，保留已退市证券与身份区间。证券身份文件记录 5921 个稳定证券标识，其中北交所 360 个。

整体价格代表与全 A 横截面严格区分。规模层使用截至当日最后一个真实快照，最多持有 45 天；没有将快照伪造为精确逐日权重。现有已验证的生效调整档案只覆盖另一指数，不能冒用于这三个规模层。覆盖精度为历史快照重建；主规模层完整生效调整目录仍不具备。快照实际覆盖如下：

| index_code   | start               | end                 |   snapshots |   rows |
|:-------------|:--------------------|:--------------------|------------:|-------:|
| 000300.SH    | 2014-01-30 00:00:00 | 2026-10-30 00:00:00 |         154 |  46200 |
| 000852.SH    | 2014-10-31 00:00:00 | 2026-10-30 00:00:00 |         145 | 145000 |
| 000905.SH    | 2014-01-30 00:00:00 | 2026-10-30 00:00:00 |         154 |  77000 |

逐年横截面覆盖见 [cross_section_coverage.csv](cross_section_coverage.csv)。个股缺价/停牌不填零收益；相邻交易日且都有有效成交与复权价格才形成收益。相关性使用窗口内始终为成员、有完整同日期收益且非零方差的平衡子集，另存其数量和对窗口成员并集的覆盖。

## 监督标签与样本覆盖

| market_id   | period        |   candidate_weeks |   continuous_valid |   categorical_valid |   history_valid |   paired_eligible |   boundary_score_eligible |
|:------------|:--------------|------------------:|-------------------:|--------------------:|----------------:|------------------:|--------------------------:|
| 000300.SH   | development   |               154 |                154 |                 154 |             154 |               154 |                       150 |
| 000300.SH   | initial_train |               255 |                255 |                 255 |             255 |               255 |                       251 |
| 000300.SH   | test          |               198 |                194 |                 194 |             198 |               194 |                       194 |
| 000852.SH   | development   |               154 |                154 |                 154 |             154 |               154 |                       150 |
| 000852.SH   | initial_train |               255 |                255 |                 255 |             255 |               255 |                       251 |
| 000852.SH   | test          |               198 |                194 |                 194 |             198 |               194 |                       194 |
| 000905.SH   | development   |               154 |                154 |                 154 |             154 |               154 |                       150 |
| 000905.SH   | initial_train |               255 |                255 |                 255 |             255 |               255 |                       251 |
| 000905.SH   | test          |               198 |                194 |                 194 |             198 |               194 |                       194 |
| 000985.SH   | development   |               154 |                154 |                 154 |             154 |               154 |                       150 |
| 000985.SH   | initial_train |               255 |                255 |                 255 |             255 |               255 |                       251 |
| 000985.SH   | test          |               198 |                194 |                 194 |             198 |               194 |                       194 |

逐年详表：[annual_coverage.csv](annual_coverage.csv)。缺失标签原因：[missing_labels.csv](missing_labels.csv)。history_valid 指当前 20 日五维可构造；5/60 日特征的个别预热缺失仍保留为空，交给训练折处理，不删掉特征。边界评分资格与标签有效性分开：2019 年末未成熟标签不进入初始字典；2022 年末跨入 2023 的开发窗口不用于开发评分；以后成熟后仍可加入对应月训练。

| field       | unit                   | definition                                                                                            |
|:------------|:-----------------------|:------------------------------------------------------------------------------------------------------|
| return      | ratio                  | P[t+H]/P[t]-1; H=20                                                                                   |
| volatility  | annualized ratio       | sqrt(252/H * sum(log(P[d]/P[d-1])^2))                                                                 |
| drawdown    | nonnegative loss ratio | max(1-P[b]/P[a]), 0<=a<=b<=H; H+1 prices                                                              |
| amihud      | 1/CNY                  | mean over days of cross-sectional median(abs(adjusted log stock return)/CNY amount)                   |
| turnover    | ratio                  | mean over days of sum(volume shares)/sum(float shares), same valid stock subset                       |
| breadth     | ratio                  | mean over days of fraction of negative valid adjusted stock returns                                   |
| correlation | Pearson correlation    | mean of stock-pair correlations on complete common-date H-day panel; membership required on every day |

| field       |   count |        mean |        std |         min |          25% |         50% |         75% |         max |
|:------------|--------:|------------:|-----------:|------------:|-------------:|------------:|------------:|------------:|
| return      |    2412 | 0.00454246  | 0.0755673  | -0.398084   | -0.0350406   | 0.00364856  | 0.038587    | 0.407944    |
| volatility  |    2412 | 0.219149    | 0.117864   |  0.042827   |  0.140825    | 0.185482    | 0.257268    | 0.799476    |
| drawdown    |    2412 | 0.0601915   | 0.0496599  |  0.0039623  |  0.0294654   | 0.0467275   | 0.0729704   | 0.459255    |
| amihud      |    2412 | 1.19966e-10 | 9.4446e-11 |  8.6567e-12 |  4.41893e-11 | 9.70853e-11 | 1.69026e-10 | 6.13548e-10 |
| turnover    |    2412 | 0.014456    | 0.00932581 |  0.00249585 |  0.00792329  | 0.0128291   | 0.0188344   | 0.0642203   |
| breadth     |    2412 | 0.491357    | 0.0516429  |  0.321976   |  0.459864    | 0.495252    | 0.527053    | 0.656772    |
| correlation |    2412 | 0.329111    | 0.159611   |  0.0549945  |  0.207772    | 0.294787    | 0.424642    | 0.868091    |

辅助结果包括下行半波动、最差单日/累计收益、路径斜率、上涨日比例、成交额、报价/有效收益/流通股本覆盖、确认停牌与未解释缺价比例、相关性面板规模。2015-07-03 沪深300窗口的 H+1 价格、手工复算七项结果见 [arithmetic_replay.json](arithmetic_replay.json)。

## 状态字典

仅 2015—2019 且在 2019-12-31 18:00 已成熟的四市场共同日期进入训练，共 1004 条，每市场等权。变换为 volatility/drawdown/amihud 的 log1p(x/训练期正值中位数)，再按训练中位数与 IQR 标准化，流动性、结构各列除 sqrt(2)。原单位标签、变换参数、模型和类别顺序均保存。

预记录比较 1—8 类 × spherical/diag/tied/full，2017/2018/2019 三段前推验证且清除训练未成熟窗口，12 次同步日历 8 周区块重采样；每次验证和重采样重新拟合其自身变换。按 BIC、验证似然、稳定性 ARI 三者的秩和选择，平分优先较少类别再按 BIC。所有选择不读取宏观或 2020 年以后数据。

选择 **K=3，tied**；BIC=7364.421，分块验证均值对数似然=-3.8673，重采样 ARI 均值=0.7951，最低=0.2104。最低稳定性明显较弱，不能声称类别在所有重采样下稳健。完整候选分数、每次 ARI、画像、训练键在 `state_dictionary/`；版本 `76bf6837dc5e32262c99`。类别按训练期收益画像排列以保证确定性，编号不代表风险等级；风险类型映射依据训练期画像固定，未设置报警工作点。

|   state_id | description                  |   n |      return |   volatility |   drawdown |      amihud |   turnover |   breadth |   correlation |
|-----------:|:-----------------------------|----:|------------:|-------------:|-----------:|------------:|-----------:|----------:|--------------:|
|          0 | 下跌；较高波动；广泛下跌     |  72 | -0.166954   |     0.608244 |  0.239776  | 1.94952e-10 |  0.0271726 |  0.523729 |      0.71052  |
|          1 | 上涨；较低波动；上涨股票较多 | 827 |  0.00033273 |     0.195799 |  0.0529199 | 1.50741e-10 |  0.0111808 |  0.484192 |      0.379181 |
|          2 | 上涨；较高波动；上涨股票较多 | 105 |  0.157379   |     0.353071 |  0.054554  | 1.01756e-10 |  0.0362716 |  0.38833  |      0.431913 |

事后归属为 `future_state_prob_*`；当前归属为 `current_state_prob_*`。未来预测概率接口须使用 `predicted_state_prob_*`，本轮没有生成。软归属熵和最高归属概率保留，未据此删除边界样本。类别数量见 [class_counts.csv](class_counts.csv)。

## 宏观输入与实际缺口

增长、物价、信用、利率、外部经济五组全部重建，主视图为带明确时间假设的历史重建；严格来源和获取时版本另存。旧来源清单的 2026-09-30 结束日期已从活动系列的经济适用期中移除，避免明明有 11 月报价却被误判制度性不适用；M1 旧定义及已结束社融口径仍有真实制度终点。按 available_at<=asof_time 从当时可得版本选择最新经济期，再计算可比变化和信息年龄；跨口径变化、累计值跨年重置和异常期距不求差。日度利率与汇率保存 5/20 个有效观测变化和变化波动。合法发布值持有到下次公布，发布断档单列，不因宏观缺失删整行。

逐系列/状态/起止/受影响周见 [macro_coverage.csv](macro_coverage.csv)，原始逐期来源缺口见 [macro_source_period_gaps.csv](macro_source_period_gaps.csv)。2014 年同口径 CFETS 国债 1Y/10Y 与派生利差各缺 245 日，影响预热并非 2015 年起标签。人民币进出口单月仍有 2020/2022 年 1—2 月及 2025 年 2 月缺口，不能把合并公告拆成单月；旧目录标记的累计 1 月缺口也不能用 1—2 月公告回填。已核对[2020 年官方合并口径](https://www.ndrc.gov.cn/fggz/fgzy/jjsjgl/202004/t20200429_1227114.html)、[2022 年官方合并发布](https://app.www.gov.cn/govdata/gov/202203/08/482607/article.html)、[2025 年官方合并发布](https://www.ccpitzj.gov.cn/art/2025/3/10/art_1229557691_47918.html)。累计同比系列中合法已有发布继续使用；这些来源不证明单月数值，未制造替代单月观测。宏观来源断档保留缺失/年龄接口，不构成 M/M+Z 不同样本。

本轮逐个股实际必需字段缺口（不是用所有可选扩展字段阻断研究）：

已观察成交记录的复权因子、元成交额、流通股本未发现空字段。

精确证券/日期明细位于 `data/market_state/coverage/field_gaps_*.parquet`。无报价且无确认停牌证据共 0 个证券日、0 只证券，见 [unexplained_quote_gaps.csv](unexplained_quote_gaps.csv) 和 `coverage/unexplained_quote_gaps.parquet`。实际检查本地湖及最新上市/退市资料、停牌事件；另外定向查询三只转板/退市北交所证券的行情、股本、因子、停牌，行情未返回而停牌记录覆盖相应区间（请求见 `bse_repair_requests.json`），没有填零收益。仍未取得独立交易所全历史名册完备证明或完整逐日成分生效档案。不能把这些精度限制说成原始实时数据认证。新补尾段复权来自供应商因子；32 个新增交易日的除权事件已逐日定向取回，见 `corporate_action_requests.json` 和 `sources/dividend/`，历史公司行为/修复依据继续保留。

## 调用、重建与验证

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run collect  # 仅缺口补齐，需网络
python -m scripts.market_state.run build    # 完整本地 A-C 重建，包括标签 GMM
python -m scripts.market_state.run verify
python -m pytest -q
```

```python
from scripts.market_state.framework import load_dataset, preprocessing
d = load_dataset(market_id='000985.SH', information_set='M+Z',
                 task='classification', fold_id='2023-01', role='train')
# task 还可取 probability / regression；所有信息集共用同一元数据和目标行。
# preprocessing() 只返回未拟合的训练折预处理接口。
```

主键为 market_id/asof_date/horizon；特征和标签分表，源/时间元数据另存。模型只使用 feature_sets.json 显式列，初始训练期标签变换与后续模型预处理独立。月度训练截止时刻取上月最后交易日 18:00，各市场日期同步。验证证据：[validation.json](validation.json)，测试实际结果：**25 passed in 9.24s**，完整运行记录见 [tests.txt](tests.txt)。Python 退出时本机 pyreadline3 控制台析构输出 WinError 0xc0000008；pytest 退出码为 0，此环境告警不属于研究测试失败。缓存为按年紧凑股票字段、北交所投影，不保存全量相关矩阵；不复制整个外部数据库。
