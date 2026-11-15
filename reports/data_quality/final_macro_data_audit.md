# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

完整候选登记65个系列ID（另含记录级口径边界），覆盖41个经济概念。当前事实池47603行、63个有值范围；保留继承事实和所有新公告版本，未用全表dropna删样本。

| series_id | ACCEPTED | NOT_COLLECTED | SEMANTIC_ERROR | SOURCE_UNREACHABLE | STRUCTURAL_NA | VINTAGE_UNVERIFIED |
| --- | --- | --- | --- | --- | --- | --- |
| cgb_10y | 2850 | 0 | 0 | 245 | 0 | 0 |
| cgb_1y | 2850 | 0 | 0 | 245 | 0 | 0 |
| core_cpi_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| cpi_mom | 153 | 0 | 0 | 0 | 0 | 0 |
| cpi_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| dr007 | 29 | 0 | 0 | 0 | 232 | 2834 |
| exports_cny_yoy | 140 | 13 | 0 | 0 | 0 | 0 |
| exports_cny_ytd_yoy | 146 | 7 | 0 | 0 | 0 | 0 |
| exports_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| fai_ytd_yoy | 140 | 0 | 0 | 0 | 13 | 0 |
| fx_reserves | 153 | 0 | 0 | 0 | 0 | 0 |
| gdp_real_yoy | 51 | 0 | 0 | 0 | 0 | 0 |
| gdp_real_ytd_yoy | 51 | 0 | 0 | 0 | 0 | 0 |
| imports_cny_yoy | 140 | 13 | 0 | 0 | 0 | 0 |
| imports_cny_ytd_yoy | 146 | 7 | 0 | 0 | 0 | 0 |
| imports_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| industrial_va_yoy | 127 | 0 | 0 | 0 | 26 | 0 |
| industrial_va_ytd_yoy | 140 | 0 | 0 | 0 | 13 | 0 |
| lpr_1y | 86 | 0 | 0 | 0 | 67 | 0 |
| m1_new_yoy | 21 | 0 | 0 | 0 | 132 | 0 |
| m1_yoy | 132 | 0 | 0 | 0 | 21 | 0 |
| m2_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| new_rmb_loans | 153 | 0 | 0 | 0 | 0 | 0 |
| pmi_mfg | 153 | 0 | 0 | 0 | 0 | 0 |
| pmi_new_orders | 153 | 0 | 0 | 0 | 0 | 0 |
| pmi_nonmfg | 153 | 0 | 0 | 0 | 0 | 0 |
| ppi_mom | 153 | 0 | 0 | 0 | 0 | 0 |
| ppi_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| retail_sales_yoy | 127 | 0 | 0 | 0 | 26 | 0 |
| retail_sales_ytd_yoy | 140 | 0 | 0 | 0 | 13 | 0 |
| rmb_loan_balance_yoy | 153 | 0 | 0 | 0 | 0 | 0 |
| rmb_loans_ytd_flow | 92 | 0 | 61 | 0 | 0 | 0 |
| shibor_1w | 3095 | 0 | 0 | 0 | 0 | 0 |
| shibor_3m | 3095 | 0 | 0 | 0 | 0 | 0 |
| shibor_on | 3095 | 0 | 0 | 0 | 0 | 0 |
| term_spread_10y_1y | 2850 | 0 | 0 | 245 | 0 | 0 |
| tsf_month_flow | 37 | 0 | 0 | 0 | 116 | 0 |
| tsf_month_flow__scope_201807 | 2 | 0 | 0 | 0 | 151 | 0 |
| tsf_month_flow__scope_201809 | 12 | 0 | 0 | 0 | 141 | 0 |
| tsf_month_flow__scope_201909 | 3 | 0 | 0 | 0 | 150 | 0 |
| tsf_month_flow__scope_202301 | 45 | 0 | 0 | 0 | 108 | 0 |
| tsf_month_flow__scope_pre_201807 | 54 | 0 | 0 | 0 | 99 | 0 |
| tsf_stock | 37 | 0 | 0 | 0 | 116 | 0 |
| tsf_stock__scope_201807 | 2 | 0 | 0 | 0 | 151 | 0 |
| tsf_stock__scope_201809 | 12 | 0 | 0 | 0 | 141 | 0 |
| tsf_stock__scope_201909 | 3 | 0 | 0 | 0 | 150 | 0 |
| tsf_stock__scope_202301 | 45 | 0 | 0 | 0 | 108 | 0 |
| tsf_stock__scope_pre_201807 | 35 | 0 | 0 | 0 | 118 | 0 |
| tsf_stock_yoy | 37 | 0 | 0 | 0 | 116 | 0 |
| tsf_stock_yoy__scope_201807 | 2 | 0 | 0 | 0 | 151 | 0 |
| tsf_stock_yoy__scope_201809 | 12 | 0 | 0 | 0 | 141 | 0 |
| tsf_stock_yoy__scope_201909 | 3 | 0 | 0 | 0 | 150 | 0 |
| tsf_stock_yoy__scope_202301 | 45 | 0 | 0 | 0 | 108 | 0 |
| tsf_stock_yoy__scope_pre_201807 | 35 | 0 | 0 | 0 | 118 | 0 |
| tsf_ytd_flow | 21 | 0 | 0 | 0 | 116 | 16 |
| tsf_ytd_flow__scope_201807 | 0 | 0 | 0 | 0 | 151 | 2 |
| tsf_ytd_flow__scope_201809 | 5 | 0 | 0 | 0 | 141 | 7 |
| tsf_ytd_flow__scope_201909 | 3 | 0 | 0 | 0 | 150 | 0 |
| tsf_ytd_flow__scope_202301 | 42 | 0 | 0 | 0 | 108 | 3 |
| tsf_ytd_flow__scope_pre_201807 | 37 | 0 | 0 | 0 | 99 | 17 |
| usdcny_fixing | 3095 | 0 | 0 | 0 | 0 | 0 |

年度社融累计另补入2014、2015、2016、2017、2019、2020、2021七个年末的有日期公告，按各自转载发布日期可得，保留舍入精度与旧供应商版本。央行2015年第四季度报告第11页的原文证实2015年1月委托贷款统计调整，已细化早期社融记录口径；所有previous/change变换均禁止跨记录口径边界。

其中4个 `__scope_unverified` ID 是来源统计范围无法认证的隔离桶，不是4条额外经济概念；保留其中全部来源记录，但不能为未知制度伪造有效区间。逐期需求网格覆盖61个已声明制度范围，其对应概念的缺口仍正常计入。

尚未达到许可质量的逐期缺口：

| series_id | status | periods | first | last |
| --- | --- | --- | --- | --- |
| cgb_10y | SOURCE_UNREACHABLE | 245 | 2014-01-02 00:00:00 | 2014-12-31 00:00:00 |
| cgb_1y | SOURCE_UNREACHABLE | 245 | 2014-01-02 00:00:00 | 2014-12-31 00:00:00 |
| dr007 | VINTAGE_UNVERIFIED | 2834 | 2014-12-15 00:00:00 | 2026-08-12 00:00:00 |
| exports_cny_yoy | NOT_COLLECTED | 13 | 2020-01-31 00:00:00 | 2026-01-31 00:00:00 |
| exports_cny_ytd_yoy | NOT_COLLECTED | 7 | 2020-01-31 00:00:00 | 2026-01-31 00:00:00 |
| imports_cny_yoy | NOT_COLLECTED | 13 | 2020-01-31 00:00:00 | 2026-01-31 00:00:00 |
| imports_cny_ytd_yoy | NOT_COLLECTED | 7 | 2020-01-31 00:00:00 | 2026-01-31 00:00:00 |
| rmb_loans_ytd_flow | SEMANTIC_ERROR | 61 | 2014-02-28 00:00:00 | 2023-05-31 00:00:00 |
| term_spread_10y_1y | SOURCE_UNREACHABLE | 245 | 2014-01-02 00:00:00 | 2014-12-31 00:00:00 |
| tsf_ytd_flow | VINTAGE_UNVERIFIED | 16 | 2020-04-30 00:00:00 | 2022-05-31 00:00:00 |
| tsf_ytd_flow__scope_201807 | VINTAGE_UNVERIFIED | 2 | 2018-07-31 00:00:00 | 2018-08-31 00:00:00 |
| tsf_ytd_flow__scope_201809 | VINTAGE_UNVERIFIED | 7 | 2018-10-31 00:00:00 | 2019-08-31 00:00:00 |
| tsf_ytd_flow__scope_202301 | VINTAGE_UNVERIFIED | 3 | 2023-02-28 00:00:00 | 2023-05-31 00:00:00 |
| tsf_ytd_flow__scope_pre_201807 | VINTAGE_UNVERIFIED | 17 | 2015-02-28 00:00:00 | 2018-05-31 00:00:00 |

DR007新增2947条真实DR007.IB加权利率，30个官方重叠日期完全一致；它们补全数字历史，不补造原始公布版本。外汇储备通过SAFE年报和2016年历史表增加晚期可验证版本，全部月份已有可追溯值；年报精度和版本差异仍保留。2025年1月M2、2026年5—6月贷款等补入有明确日期的原文或当期转载。

社融自2023年1月新增报告机构范围，四个社融概念各增加独立scope ID；2019年12月范围截至2022年12月。人民币贷款累计不能用社融中人民币贷款分项替代，也不将不同版本当月流量相加后冒称官方累计值。人民币贸易缺失月份仍标记真实缺口，未因合并新闻发布而自动豁免。

观察期、市场交易日、公告时间、实际版本可得时间、下载时间和成分生效时间分别保存。只有 `research_available_at <= asof_time` 的许可版本可进入对应视图。`quote_reconstructed` 对 DR007 明确使用另存的历史收盘可得假设；其真实版本可得时间仍保留，不能称为严格PIT。市场 v2 和 v4 连续扩展均明确为历史报价重建。

公告日期未知时不得由 URL 年份、文件名或观测月猜测。官方后期年报只能在年报发布日期后使用；同一时刻上载的海关月报按已证明的刊期顺序保存。LPR 月末是归档月份，实际定盘在 `observation_date`；春节前发布的 PMI 按原公告日期使用。

新增贷款、贷款累计与贷款余额同比另保留2015年纳入非银行金融机构拆放、2023年扩展报告机构的逐条scope；周度previous/change遇口径边界留空，父记录口径写入特征血缘。2026年3月与6月社融单月按有日期的报道补入保守版本，六月万亿元报道的舍入精度为100亿元。商务部未标版本API的三月值52240与当期报道52260不同，候选原始返回保留且不倒填成当期版本。

