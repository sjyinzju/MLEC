# A股市场数据审计报告

审计日期：2026-11-04（Asia/Shanghai）。审计执行时间：2026-11-04T15:07:08.859290+00:00 至 2026-11-04T15:23:40.689779+00:00（UTC）。

## 结论与边界

本地数据足以支持沪深300的历史价格风险研究：`000300.SH` 在 **2015-01-05 至 2026-09-22** 的 **2,850** 个本地交易日均有行情，OHLC、前收盘、涨跌幅、成交量和成交额无空值、无所检价量异常。2016年以前确有2015年行情；不能把下载起点误设为2016年，也不能假设已有2015年以前的沪深300价格历史。

全库不能认证为完整：有57个指数请求无实际数据、Shibor两表未完成、权限缺失数据集、指数权重覆盖限制及北交所日历缺失。股票、财务、事件、宏观等各表历史范围不同。`SUCCESS`、水位线、已有报告和本次页脚检查均不单独等同于研究完整性。

全程只读访问 `E:\QuantData` 与 `E:\quant`，未调用原项目CLI、Registry初始化、下载器、修复器或联网接口；未读取 `.env`。新脚本、诊断表、报告及查询临时文件均在 `E:\MLEC`。本轮没有计算特征、状态、标签值、训练或回测；日期窗口检查仅证明观测是否存在。

## 1. 存储、来源与口径

数据来源由 `E:\quant\src\quant\data\sources\tushare.py` 的适配器和官方接口定义确认，是 Tushare。表定义、字段含义、成交量单位“手”、成交额单位“千元”等采用本地 `config/official_api_schema.json` 中缓存的定义；没有联网重新核验文档或独立核对交易所行情。逐字段来源URL已列入 `dataset_inventory.csv`。

共清点 **1,620,204** 文件、**1,294,773** 个 Parquet（105.64 GB，十进制），包含Raw、当前Canonical、停用历史版本和审计样本。完整路径、大小、修改时间和文件类型见 [file_manifest.csv](../audit/file_manifest.csv)。

| 分层 | 文件数 | 实际用途 |
| --- | --- | --- |
| quant.duckdb | 1 | 注册表和读取Parquet的逻辑视图 |
| 00_raw | 434,934 | Tushare原始批次及伴随JSON；包括重复观察、空响应和未发布页 |
| 10_canonical | 1,077,205 | 标准化版本文件；研究只能选择active路径及明确版本 |
| 40_qlib | 105,854 | 两个既有行情回放导出；不作本课程主要输入 |
| 80_quarantine | 113 | 隔离质量异常及失败批次证据 |
| 90_metadata | 939 | 请求意图、进度、锁、回收登记备份等 |
| reports | 1,158 | 旧审计、冻结注册表、PIT测试临时库、核验材料 |

`20_pit / 30_features / 50_predictions / 60_backtests / 70_live` 目录没有文件；目录存在不表示已有课程样本或模型结果。当前发现 67 个有有效Canonical的数据集；下载代码定义范围共 89 项（含未下载项）。主库不是另存一份全部行情：`canonical_*` 视图引用注册文件，先按`_row_hash + _ingested_at`去重，再按自然/版本键取最后观察。自然键空缺的事件接口使用内容哈希身份。物理重观测/版本行不能误报为逻辑重复。

共 139 个辅助数据库（138个DuckDB及1个SQLite）另加主DuckDB；所有数据库以只读方式打开并读取表清单，SQLite `quick_check`通过。辅助数据库为备份、冻结注册表、PIT测试scratch和审计证据，不是独立市场数据源；未逐库解码其所有引用文件，完整内容为 **UNKNOWN**。见 [database_inventory.csv](../audit/database_inventory.csv)。365个CSV属于既有审计输出，逐文件见清单；未将其视作新下载行情，其完整内容为UNKNOWN。

## 2. 实际文件与下载状态核验

- 注册的 **217,467** 个Raw Parquet全部存在；逐文件读取页脚，行数全部与登记一致，坏页脚/行数不符均为0。逐文件证据见 [raw_file_checks.csv](../audit/raw_file_checks.csv)。Raw全列完整解码抽样 **201** 个文件，全部成功；未完整解码所有Raw数据页，未抽到的数据页损坏仍为 **UNKNOWN**。
- 当前有效Canonical **8,540** 文件全部存在，全部SHA-256与登记值一致，页脚与登记行数一致。对全部数据集所有列进行分年或整表实际聚合，完成逻辑行数、类型、空值、最小最大值、数值非有限值、键重复和适用异常规则检查。未发现当前有效数据读取损坏。明细见 [active_file_checks.csv](../audit/active_file_checks.csv)、[active_file_hashes.csv](../audit/active_file_hashes.csv)。
- 注册Canonical总文件 **1,077,188**，全部存在，其中1,068,648个已停用；停用文件完整解码抽样 **161** 个通过。其余停用文件的数据页/哈希为 **UNKNOWN**，不能笼统称129万Parquet全量无损。
- 另有 **16** 个未登记Canonical Parquet及 **3** 个`.partial`（一个行业成分Parquet、两个进度JSON）。这19个文件已只读解析且可读，但均未被注册为当前有效输入；可读不代表已完成原子发布。未删除、移动、改写它们。路径见 [lineage_summary.json](../audit/lineage_summary.json)、[unpublished_file_checks.csv](../audit/unpublished_file_checks.csv)。
- 财务Raw存在大量物理schema签名，可能包含全空列推断差异等；当前标准化层逐表核对了官方预期字段。所有原始schema变种逐一语义等价的认证为 **UNKNOWN**，不把签名差异直接等同于损坏。

任务库实际计数：{'SUCCESS': 183199, 'FAILED_PERMANENT': 57, 'FAILED_RETRYABLE': 80, 'PENDING': 174}。失败/待处理共311项，已无`RUNNING`状态；不据此推断操作系统后台进程状态。

| 数据集 | 未完成状态 | 实际依据 |
| --- | --- | --- |
| index_daily | 57 FAILED_PERMANENT / source_empty_exhausted | 9655个请求代码中9598个有实际行情，57个无行；全部失败代码在明细中 |
| shibor_quote | 40 FAILED_RETRYABLE + 88 PENDING | 包含频率、网络及中断错误；实际历史并不连续 |
| shibor_lpr | 40 FAILED_RETRYABLE + 86 PENDING | 包含频率、网络错误；实际历史并不连续 |

[incomplete_tasks.csv](../audit/incomplete_tasks.csv) 保留请求代码/日期/状态，[task_status.csv](../audit/task_status.csv) 为逐接口汇总。持久化 `bootstrap_request.json` 的目标仍为 **2015-01-01—2026-09-22**；最后记录不是更新到审计当天的证据。2026-10-04的旧修复文档称`share_float`未完成，但现在该接口已无失败/待处理任务，实际行数与日期已重新查询，不能继续照抄旧阻断结论。当前Raw保留分页溢出及重试数据，其总行数不是可用逻辑行数。

代码核验：Planner按SSE/SZSE/BSE规划交易日历，指数基本信息按6个market获取；指数行情为基准代码加基本信息中`.SH/.SZ/.CSI/.BJ`范围。已核实在范围内的基本信息指数没有未规划遗漏（0个）；范围外代码不作失败结论。指数权重只规划11个BENCHMARKS，并不是全部10604个指数。`index_member_all`是申万行业历史成分，不是沪深300成分表。分页、请求行数上限和隔离机制在代码中存在，但不等于来源完整性；本轮以实际行、日历和键关联验证补足。代码指纹见 [source_code_hashes.json](../audit/source_code_hashes.json)。

## 3. 重点指数与交易日历

| 代码 | 名称 | 实际起点 | 实际终点 | 行数 | 目标区间缺少交易日 | 价量异常行 |
| --- | --- | --- | --- | --- | --- | --- |
| 000001.SH | 上证指数 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000300.SH | 沪深300 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000905.SH | 中证500 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000852.SH | 中证1000 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000016.SH | 上证50 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000688.SH | 科创50 | 2019-12-31 | 2026-09-22 | 1632 | 1218 | 1 |
| 399001.SZ | 深证成指 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 399006.SZ | 创业板指 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 399303.SZ | 国证2000 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 000510.SH | 中证A500 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |
| 899050.BJ | UNKNOWN | 2022-04-29 | 2026-09-22 | 1069 | 1781 | 1 |
| 399300.SZ | 沪深300 | 2015-01-05 | 2026-09-22 | 2850 | 0 | 0 |

科创50与北交所代码的较晚起点不能自动认定为下载失败，应区分指数历史定义/回溯区间与请求缺漏；各自已观测区间的内部缺日另见 `dataset_coverage.csv`。北交所代码名称在基本信息中缺失，标记UNKNOWN。中证A500等指数存在发布前回溯行情：基本信息的`base_date/list_date`与实际价格起点分开列于 [benchmark_master_definitions.csv](../audit/benchmark_master_definitions.csv)，不能将回溯行情当作当时已发布、可实时使用的指数。

科创50的2019-12-31、899050.BJ的2022-04-29各有一条初始基点记录，只有close/vol/amount，open/high/low/pre_close/pct_chg为空；这两条不具备完整OHLC。它们各自起点至末日没有内部SSE开放日缺口，但北交所仍缺独立日历认证。详见`benchmark_null_price_rows.json`，不将初始基点空值冒充普通完整日K线。

`000300.SH`与`399300.SZ`是两个本地沪深300代码口径，价量差异核对见 [csi300_code_comparison.json](../audit/csi300_code_comparison.json)；研究固定选择`000300.SH`，不要拼成重复样本。当前Raw中这两个代码的实际最早/最晚日期见 [csi300_raw_bounds.json](../audit/csi300_raw_bounds.json)。

两代码同日close有335日不完全相同，最大绝对差0.0009点；157日vol或amount不完全相同。固定代码也可避免混入这种来源口径差异。

本地交易日历只有SSE和SZSE：各4693条日历日，范围 **2013-12-27—2026-11-01**，各3120个开放日；审计目标区间内2850个开放日。沪深日历无日期缺口，开放标记一致，`pretrade_date`与前一开放日一致；BSE没有有效行，不能认证北交所。日历与交易所最新官方公告的独立比对为 **UNKNOWN**。**2026-11-02—11-04日历缺失**；本地已知日历显示市场行情9月22日之后至少22个开放日没有更新，另有11月尾部3个日历日尚未核实，见 [staleness.json](../audit/staleness.json)。这不影响选择截至9月22日的历史研究，但不能称当前实时数据库。

全部9598个实有行情代码的内部SSE交易日诊断见 [all_index_calendar_diagnostics.csv](../audit/all_index_calendar_diagnostics.csv)。跨境、债券和特殊指数可能不遵循同一日历；该诊断标记需要核对的区间，不能机械地把每个SSE差日都认定为下载错误。57个彻底无行代码及中文名称见 [index_code_request_reconciliation.csv](../audit/index_code_request_reconciliation.csv)。

隔离记录中有134条指数异常行，涉及16个代码，主要包括`000999.SH`（101行）等；全部明细见 [index_quarantined_rows.csv](../audit/index_quarantined_rows.csv)。**沪深300两代码均不在该隔离清单**。故“全表含隔离缺口”和“沪深300区间完整”可以同时成立；不得用前者否定已查证的主研究序列，也不得用后者认证全部指数。

## 4. 指数基本信息、每日指标和权重

`index_basic`实际10604行；`index_type`列全部为空，其余每列空值见清单，不能按21208物理行推断有21208个独立指数。`000300.SH`的`index_dailybasic`同样2850日齐全，12个业务字段（包括代码、日期、市值、股本、换手率、PE、PE_TTM、PB）全部无空值，可以直接用于该区间的扩展指数研究。`399300.SZ`此表缺2026-03-16一日，不能无核查地交换代码；`399303.SZ/000510.SH/899050.BJ`在此表无行；科创50该表始于2020-07-23，晚于其回溯价格起点。逐代码覆盖见 [index_dailybasic_symbols.csv](../audit/index_dailybasic_symbols.csv)，未以该表替代指数价格表。

权重为快照，按快照检查成员数、权重总和和月份连续性，而非要求每天都有记录：

| 指数 | 起点 | 终点 | 快照数 | 月份数 | 成员数范围 | 权重和范围 | 内部缺失月份 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 000001.SH | 2015-01-30 | 2026-08-31 | 140 | 140 | 1038–2251 | 99.8200–100.0490 | 无 |
| 000016.SH | 2015-01-30 | 2026-08-31 | 140 | 140 | 50–50 | 99.9900–100.0700 | 无 |
| 000300.SH | 2015-01-30 | 2026-08-31 | 140 | 140 | 300–300 | 99.9300–100.0600 | 无 |
| 000510.SH | 2024-09-30 | 2026-08-31 | 24 | 24 | 500–500 | 99.9870–100.0130 | 无 |
| 000688.SH | 2020-07-31 | 2026-08-31 | 74 | 74 | 50–50 | 99.9960–100.0050 | 无 |
| 000852.SH | 2015-01-30 | 2026-08-31 | 140 | 140 | 1000–1000 | 99.9100–100.0900 | 无 |
| 000905.SH | 2015-01-30 | 2026-08-31 | 140 | 140 | 500–500 | 99.9200–100.1200 | 无 |
| 399001.SZ | 2015-01-30 | 2026-08-31 | 140 | 140 | 40–500 | 99.9900–100.0300 | 无 |
| 399006.SZ | 2015-01-30 | 2026-08-31 | 140 | 140 | 100–100 | 99.9993–100.0200 | 无 |
| 399303.SZ | 2015-01-30 | 2026-08-31 | 140 | 140 | 1470–2000 | 99.9965–100.2900 | 无 |
| 899050.BJ | 2022-11-30 | 2026-08-31 | 46 | 46 | 50–50 | 99.9960–100.0050 | 无 |

快照不提供逐次调仓完整生效时间和历史首次发布时间；仅有月度持仓无法认证逐日精确成分或严格可得时间。不能用当前成分倒推历史。没有权重行的已规划基准也须作为范围缺口处理；所有目标代码见`dataset_coverage.csv`。尾部未观察到2026年9月权重，不在没有来源发布时间证据时断言所有9月请求都应有快照，但不能声称权重已覆盖9月22日。单纯使用官方沪深300指数价量计算风险不依赖成分权重。

## 5. 股票行情、指标、复权与数据质量

股票行情实际 **11,764,739** 行，每日基本指标 **11,674,467** 行，复权因子 **12,277,865** 行；三表均有2015年记录。全部覆盖目标区间的2850个交易日，但“某天有股票数据”不能证明所有当日应交易股票齐备。

| 左表 | 需要右表 | 代码后缀 | 无法匹配的键 |
| --- | --- | --- | --- |
| adj_factor | daily | BJ | 210397 |
| adj_factor | daily | SH | 106050 |
| adj_factor | daily | SZ | 196679 |
| daily | daily_basic | BJ | 90362 |
| daily | stk_limit | BJ | 91014 |
| daily | stk_limit | SH | 1 |
| daily | stk_limit | SZ | 1129 |
| daily_basic | daily | SH | 42 |
| daily_basic | daily | SZ | 48 |

所有行情键均有复权因子；沪深行情键均有每日基本指标，缺少基本指标的90362个键全属`.BJ`。反向每日基本指标有90个沪深键找不到行情；因子有513126个键找不到行情，可能涉及停牌、退市与来源覆盖，逐项真实原因仍为 **UNKNOWN**，不能自动补零或据此删除数据。涨跌停价表还有1130个沪深行情键无法匹配。按年份、代码、日期的明细见 [stock_dependency_reconciliation.csv](../audit/stock_dependency_reconciliation.csv)、[stock_dependency_gap_by_code.csv](../audit/stock_dependency_gap_by_code.csv)。

股票`daily`的open/high/low/close/vol/amount无空值，但pre_close/change/pct_chg各有224条空值；可能涉及首次交易记录，具体原因未逐条认证。研究股票收益时应明确采用相邻有效close还是来源pct_chg，不以日期覆盖完整推断每个收益字段无缺失。

全表数值规则结果：| 数据集 | 规则 | 异常数 |
| --- | --- | --- |
| index_daily | zero_close | 1472 |

特别发现`index_daily`有1472条零收盘价，集中在`H50060.CSI`（457日）、`395011.SZ`（297日）、`931997.CSI`（198日）、`H50059.CSI`（196日）、`H30402.CSI`（192日）、`H30401.CSI`（132日）。这些序列不能直接用作对数收益/价格比率输入；本轮保留并标记，尚未判断零值是来源特殊定义还是错误。沪深300不涉及这些代码。另有1941条价格跳变/涨跌幅一致性候选，明细`index_price_issues.csv`仅为筛查，并非1941条已确认错误。

日期字段检查发现`disclosure_date.modify_date`有1200个逻辑记录不符合单一YYYYMMDD格式，实际样例为逗号分隔多个修改日期；`pledge_detail`的`start_date/end_date/release_date`分别有25/5/8条为年月或年份等低精度表示。不能把这些值无声解析为空后声称无缺失，需按字段语义另定解析规则。明细见`date_field_validity.csv`与`invalid_date_examples.json`；不是沪深300研究阻断。

全部逻辑数据集均已实际按键检查重复；每表的逻辑重复行、物理重复观察、相同内容再观察、版本差异记录在`audit/datasets/<数据集>.json`和覆盖表，不把取最新视图的0重复误当作物理输入没有重复。全部业务字段缺失率见 [business_field_nulls.csv](../audit/business_field_nulls.csv)，字段本身是否缺失、实际类型、最小最大值、非有限值数在 [dataset_inventory.csv](../audit/dataset_inventory.csv)。全空业务字段如下：

| 数据集 | 全空字段 |
| --- | --- |
| balancesheet | agency_bus_liab, depos_received, pledge_borr |
| express | perf_summary, remark |
| fund_basic | exp_return, trustee |
| income | transfer_surplus_rese, transfer_housing_imprest, withdra_legal_surplus, withdra_legal_pubfund, withdra_biz_devfund, withdra_rese_fund, withdra_oth_ersu, workers_welfare, capit_comstock_div |
| index_basic | index_type |
| stk_seasoned | pe_issue, clw_between_inst_pub, ex_right_dt |

以上空值不自动认定为下载失败。例如亏损PE为空、财务行业不适用列为空、北交所早期数据覆盖差异需分别解释。完整金融经济语义校验、来源错误数值的独立真值核对、极端值究竟错误还是经济事件，为 **UNKNOWN**；本轮通过明确价量规则、全列范围和非有限值筛查给出可复核候选，不以任意统计阈值删除极端行情。`daily_basic`估值、分红、自由流通股等列的不同空值率意味着扩展研究必须按字段设定样本口径。

## 6. 所有数据集实际范围与用途

下表为逐表实际查询；日期采用其事实日期字段，股票主表的上市日期、财报公告日期、未来解禁日期、宏观月份均不是共同的行情覆盖起点。没有统一事实日期的表查了所有原始日期列，详细边界见各表JSON的`date_bounds`。空值字段数仅统计业务列。事件/快照/宏观表在交易日覆盖表中的差日仅作诊断，不意味着它们应逐交易日有行。

| 数据集 | 类别/用途 | 逻辑行数 | 日期字段 | 实际区间 | 2016年前行数 | 有空值字段数 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| adj_factor | market | 12,277,865 | trade_date | 2015-01-05 → 2026-09-22 | 675358 | 0 | 已核行数；整体完整性 UNKNOWN |
| bak_basic | status | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| balancesheet | financial | 317,069 | ann_date | 2015-01-01 → 2026-09-01 | 17818 | 151 | 已核行数；整体完整性 UNKNOWN |
| block_trade | event | 559,254 | trade_date | 2015-01-05 → 2026-09-22 | 22859 | 2 | 已核行数；整体完整性 UNKNOWN |
| bse_mapping | master | 248 | 无统一事实日期 | UNKNOWN → UNKNOWN | UNKNOWN | 0 | 已核行数；整体完整性 UNKNOWN |
| cashflow | financial | 315,608 | ann_date | 2015-01-01 → 2026-09-03 | 14323 | 90 | 已核行数；整体完整性 UNKNOWN |
| ci_daily | industry | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| ci_index_member | industry | 0 | in_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| cn_cpi | macro | 140 | month | 201501 → 202608 | 12 | 0 | 已核行数；整体完整性 UNKNOWN |
| cn_gdp | macro | 46 | quarter | 2015Q1 → 2026Q2 | 4 | 0 | 已核行数；整体完整性 UNKNOWN |
| cn_m | macro | 140 | month | 201501 → 202608 | 12 | 0 | 已核行数；整体完整性 UNKNOWN |
| cn_pmi | macro | 141 | month | 201501 → 202609 | 12 | 23 | 已核行数；整体完整性 UNKNOWN |
| cn_ppi | macro | 140 | month | 201501 → 202608 | 12 | 0 | 已核行数；整体完整性 UNKNOWN |
| cn_schedule | macro | 131 | publish_date | 2026-01-04 → 2026-09-30 | 0 | 1 | 已核行数；整体完整性 UNKNOWN |
| daily | market | 11,764,739 | trade_date | 2015-01-05 → 2026-09-22 | 575184 | 5 | 已核行数；整体完整性 UNKNOWN |
| daily_basic | market | 11,674,467 | trade_date | 2015-01-05 → 2026-09-22 | 570310 | 17 | 已核行数；整体完整性 UNKNOWN |
| daily_info | context | 55,398 | trade_date | 2015-01-05 → 2026-09-22 | 6100 | 10 | 已核行数；整体完整性 UNKNOWN |
| disclosure_date | financial | 300,176 | actual_date | 1990-12-31 → 2026-08-31 | 111450 | 2 | 已核行数；整体完整性 UNKNOWN |
| dividend | financial | 212,937 | ann_date | 1991-03-17 → 2026-09-22 | 5679 | 12 | 已核行数；整体完整性 UNKNOWN |
| etf_basic | fund | 0 | list_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| etf_index | fund | 0 | 无统一事实日期 | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| etf_limit | fund | 2,235,250 | trade_date | 2019-06-26 → 2026-09-22 | 0 | 1 | 已核行数；整体完整性 UNKNOWN |
| etf_share_size | fund | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| express | financial | 20,609 | ann_date | 2015-01-06 → 2026-08-24 | 1630 | 28 | 已核行数；整体完整性 UNKNOWN |
| fina_audit | financial | 63,516 | ann_date | 2015-01-01 → 2026-08-31 | 4133 | 2 | 已核行数；整体完整性 UNKNOWN |
| fina_indicator | financial | 389,530 | ann_date | 2015-04-07 → 2026-09-30 | 17958 | 163 | 已核行数；整体完整性 UNKNOWN |
| fina_mainbz | financial | 1,780,812 | end_date | 2015-02-28 → 2026-06-30 | 126768 | 3 | 已核行数；整体完整性 UNKNOWN |
| forecast | financial | 83,958 | ann_date | 2015-01-01 → 2026-09-18 | 7581 | 8 | 已核行数；整体完整性 UNKNOWN |
| fund_adj | fund | 2,958,557 | trade_date | 2015-01-05 → 2026-09-22 | 126071 | 0 | 已核行数；整体完整性 UNKNOWN |
| fund_basic | master | 2,912 | list_date | 1998-04-07 → 2026-09-28 | 684 | 16 | 已核行数；整体完整性 UNKNOWN |
| fund_daily | fund | 2,770,397 | trade_date | 2015-01-05 → 2026-09-22 | 123519 | 0 | 已核行数；整体完整性 UNKNOWN |
| fund_div | fund | 4,083 | ann_date | 2015-01-07 → 2026-09-22 | 138 | 12 | 已核行数；整体完整性 UNKNOWN |
| fund_nav | fund | 3,040,262 | nav_date | 2015-01-04 → 2026-09-22 | 141238 | 6 | 已核行数；整体完整性 UNKNOWN |
| fund_portfolio | fund | 0 | ann_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| fund_share | fund | 2,058,878 | trade_date | 2015-01-01 → 2026-09-22 | 80651 | 0 | 已核行数；整体完整性 UNKNOWN |
| gz_index | macro | 644 | date | 2015-01-02 → 2019-03-04 | 272 | 0 | 已核行数；整体完整性 UNKNOWN |
| hsgt_top10 | flow | 50,010 | trade_date | 2015-01-05 → 2026-09-22 | 2310 | 5 | 已核行数；整体完整性 UNKNOWN |
| income | financial | 304,376 | ann_date | 2015-01-01 → 2026-09-03 | 14569 | 87 | 已核行数；整体完整性 UNKNOWN |
| index_basic | master | 10,604 | list_date | 1991-04-04 → 2026-09-17 | 3699 | 6 | 已核行数；整体完整性 UNKNOWN |
| index_classify | master | 870 | 无统一事实日期 | UNKNOWN → UNKNOWN | UNKNOWN | 1 | 已核行数；整体完整性 UNKNOWN |
| index_daily | index | 23,785,538 | trade_date | 2015-01-01 → 2026-09-22 | 1537966 | 9 | 部分可用，见专项 |
| index_dailybasic | index | 40,888 | trade_date | 2015-01-05 → 2026-09-22 | 3172 | 0 | 已核行数；整体完整性 UNKNOWN |
| index_member_all | industry | 7,920 | in_date | 1984-05-09 → 2026-09-24 | 3259 | 1 | 已核行数；整体完整性 UNKNOWN |
| index_weight | index | 862,089 | trade_date | 2015-01-30 → 2026-08-31 | 58548 | 0 | 部分可用，见专项 |
| limit_list_d | event | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| margin | flow | 6,579 | trade_date | 2015-01-05 → 2026-09-22 | 488 | 1 | 已核行数；整体完整性 UNKNOWN |
| margin_detail | flow | 6,436,851 | trade_date | 2015-01-05 → 2026-09-22 | 221848 | 9 | 已核行数；整体完整性 UNKNOWN |
| margin_secs | flow | 7,858,001 | trade_date | 2015-01-05 → 2026-09-22 | 98748 | 0 | 已核行数；整体完整性 UNKNOWN |
| moneyflow | flow | 11,421,685 | trade_date | 2015-01-05 → 2026-09-22 | 569714 | 0 | 已核行数；整体完整性 UNKNOWN |
| moneyflow_cnt_ths | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_dc | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_hsgt | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_ind_dc | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_ind_ths | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_mkt_dc | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| moneyflow_ths | flow | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| namechange | master | 14,218 | start_date | 1990-12-01 → 2026-09-30 | 8276 | 2 | 已核行数；整体完整性 UNKNOWN |
| new_share | master | 3,252 | ipo_date | 2015-01-12 → 2026-09-21 | 220 | 1 | 已核行数；整体完整性 UNKNOWN |
| pledge_detail | event | 220,409 | ann_date | 2015-01-01 → 2026-09-22 | 6549 | 9 | 已核行数；整体完整性 UNKNOWN |
| pledge_stat | event | 1,646,734 | end_date | 2014-03-07 → 2026-09-18 | 140355 | 0 | 已核行数；整体完整性 UNKNOWN |
| repurchase | event | 62,681 | ann_date | 2015-01-01 → 2026-09-22 | 660 | 6 | 已核行数；整体完整性 UNKNOWN |
| sf_month | macro | 140 | month | 201501 → 202608 | 12 | 1 | 已核行数；整体完整性 UNKNOWN |
| share_float | event | 6,270,894 | ann_date | 2005-08-19 → 2026-09-19 | 37270 | 2 | 已核行数；整体完整性 UNKNOWN |
| shibor | macro | 2,904 | date | 2015-01-04 → 2026-09-22 | 249 | 0 | 已核行数；整体完整性 UNKNOWN |
| shibor_lpr | macro | 365 | date | 2015-01-04 → 2019-06-28 | 88 | 0 | 部分可用，见专项 |
| shibor_quote | macro | 5,830 | date | 2015-01-04 → 2019-03-29 | 1170 | 0 | 部分可用，见专项 |
| st | status | 0 | pub_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| stk_alert | event | 0 | start_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| stk_high_shock | event | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| stk_holdernumber | event | 473,194 | ann_date | 2015-01-05 → 2026-09-22 | 13148 | 1 | 已核行数；整体完整性 UNKNOWN |
| stk_holdertrade | event | 160,788 | ann_date | 2015-01-01 → 2026-09-22 | 10656 | 6 | 已核行数；整体完整性 UNKNOWN |
| stk_limit | market | 12,046,364 | trade_date | 2015-01-05 → 2026-09-22 | 665312 | 1 | 已核行数；整体完整性 UNKNOWN |
| stk_managers | event | 363,487 | ann_date | 2015-01-01 → 2026-09-22 | 18638 | 9 | 已核行数；整体完整性 UNKNOWN |
| stk_rewards | event | 1,642,908 | ann_date | 1992-05-26 → 2026-09-21 | 577004 | 4 | 已核行数；整体完整性 UNKNOWN |
| stk_seasoned | event | 9,736 | ann_date | 2015-01-01 → 2026-09-22 | 1218 | 61 | 已核行数；整体完整性 UNKNOWN |
| stk_shock | event | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| stock_basic | master | 5,907 | list_date | 1990-12-01 → 2026-09-23 | 2897 | 6 | 已核行数；整体完整性 UNKNOWN |
| stock_company | master | 6,294 | 无统一事实日期 | UNKNOWN → UNKNOWN | UNKNOWN | 11 | 已核行数；整体完整性 UNKNOWN |
| stock_hsgt | status | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| stock_st | status | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| suspend_d | status | 334,629 | trade_date | 2015-01-05 → 2026-09-22 | 99057 | 1 | 已核行数；整体完整性 UNKNOWN |
| sw_daily | industry | 0 | trade_date | UNKNOWN → UNKNOWN | UNKNOWN | 0 | MISSING |
| sz_daily_info | context | 41,454 | trade_date | 2015-01-05 → 2026-09-22 | 3904 | 5 | 已核行数；整体完整性 UNKNOWN |
| top10_floatholders | event | 2,098,029 | ann_date | 2015-01-17 → 2026-09-30 | 108035 | 3 | 已核行数；整体完整性 UNKNOWN |
| top10_holders | event | 2,319,216 | ann_date | 2014-12-26 → 2026-09-30 | 116365 | 3 | 已核行数；整体完整性 UNKNOWN |
| top_inst | event | 2,388,918 | trade_date | 2015-01-05 → 2026-09-22 | 189706 | 4 | 已核行数；整体完整性 UNKNOWN |
| top_list | event | 198,701 | trade_date | 2015-01-05 → 2026-09-22 | 18204 | 10 | 已核行数；整体完整性 UNKNOWN |
| trade_cal | master | 9,386 | cal_date | 2013-12-27 → 2026-11-01 | 1470 | 0 | 已核行数；整体完整性 UNKNOWN |
| wz_index | macro | 2,703 | date | 2015-01-04 → 2026-09-22 | 245 | 9 | 已核行数；整体完整性 UNKNOWN |

未下载数据集：`bak_basic`, `ci_daily`, `ci_index_member`, `etf_basic`, `etf_index`, `etf_share_size`, `fund_portfolio`, `limit_list_d`, `moneyflow_cnt_ths`, `moneyflow_dc`, `moneyflow_hsgt`, `moneyflow_ind_dc`, `moneyflow_ind_ths`, `moneyflow_mkt_dc`, `moneyflow_ths`, `st`, `stk_alert`, `stk_high_shock`, `stk_shock`, `stock_hsgt`, `stock_st`, `sw_daily`。主要为接口权限拒绝；`moneyflow_hsgt`在代码定义范围但不在当前持久化bootstrap endpoints，不能标成下载成功。接口探测`empty`也不能当无权限：如`namechange/suspend_d/index_member_all`探测为空但实际有历史数据。逐项能力标志见`capabilities.json`，以实际Canonical是否有行判定存在。

## 7. 未核实项与复现

UNKNOWN项包括：所有未抽样Raw/停用文件的数据页损坏、辅助库/旧CSV完整内容、全部历史证券应交易日真值、独立交易所价量真值、历史成分准确发布/生效时间、财务事件宏观在首次采集之前的真实修订轨迹、未来日历尾部、各稀疏数据集的来源全集完整性。全量文件存在、页脚可读、哈希匹配和本地规则通过各有明确范围，不能扩展成全市场无误认证。

主数据库起止大小和修改时间一致：**True**；原始文件仅只读打开，本轮未发起任何源目录写操作。输出脚本可用原项目现有Python环境离线复现，无需安装依赖：

```powershell
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\explore_audit.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_market_data.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_files_and_storage.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_research_dependencies.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_remaining_checks.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_index_scope.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\audit_anomaly_details.py
E:\quant\.venv\Scripts\python.exe -X utf8 E:\MLEC\scripts\build_audit_reports.py
```

审计按单线程DuckDB、2GB以内内存限制和分年查询执行，大表不整表载入Python；DuckDB临时落盘限于课程目录。曾在初次整表视图查询时触发2GB内存限制，已改为稳定日期键分年读取并重跑；最终报告仅纳入重跑成功的查询结果。检查清单见`audit_run.json`、`query_log.json`和逐数据集JSON。
