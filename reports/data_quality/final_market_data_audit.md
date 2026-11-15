# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

本轮检查了 67 个外部已注册数据源，逐项标明 REQUIRED / CANDIDATE / OUT_OF_SCOPE 及理由。研究期为2015-01-05至2026-09-22，独立预热从2014年开始。

| dataset_id | rows | actual_data_start | actual_data_end | quality_status |
| --- | --- | --- | --- | --- |
| index_daily | 21665 | 20140102 | 20260922 | FAIL |
| index_daily_basic | 21474 | 20140102 | 20260922 | QUALIFIED |
| stock_daily | 11981370 | 20140102 | 20260922 | QUALIFIED |
| stock_daily_basic | 11981381 | 20140102 | 20260922 | FAIL |
| stock_adjustment | 12333672 | 20140102 | 20260922 | FAIL |
| stock_master_history | 5559 | 1990-12-01 00:00:00 | 2026-09-22 00:00:00 | QUALIFIED |
| stock_name_history | 13851 | 19901201 | 20260930 | QUALIFIED |
| stock_trading_status | 12313921 | 20140102 | 20260922 | QUALIFIED |
| index_constituents_history | 19500 | 2015-05-20 00:00:00 | 2026-06-15 00:00:00 | FAIL |
| index_weights_history | 576892 | 20150130 | 20260831 | QUALIFIED |
| trade_calendar | 9386 | 20131227 | 20261101 | QUALIFIED |
| index_identity | 7 | 19910715 | 20141017 | QUALIFIED |
| stock_limits | 12309435 | 20140102 | 20260922 | QUALIFIED |
| margin_market | 6579 | 20150105 | 20260922 | QUALIFIED |
| margin_security | 5751345 | 20150105 | 20260922 | QUALIFIED |
| stock_moneyflow | 11978894 | 20140102 | 20260922 | FAIL |
| exchange_activity_sh | 55398 | 20150105 | 20260922 | QUALIFIED |
| exchange_activity_sz | 41454 | 20150105 | 20260922 | QUALIFIED |
| stock_connect_top10 | 50010 | 20150105 | 20260922 | QUALIFIED |
| stock_dividend_events | 212115 | 19910317 | 20260922 | QUALIFIED |
| market_data_quality | 4535515 | 20140102 | 20260922 | QUALIFIED |

七个指定指数均有3095个应有交易日，共21665行。中证1000在2014-10-17发布前的191条回溯行情单独标记，不能解释为当时可投资信息。基础估值表在发布后完整覆盖，共21474行；其字段非空不构成独立精度认证。

| status | observations |
| --- | --- |
| OBSERVED | 11981370 |
| SUSPENDED_OFFICIAL_EVIDENCE | 11882 |
| SUSPENDED_SOURCE_RECORDED | 320669 |

字段级未认证/缺失/冲突计数（可追溯至逐证券逐日期质量表）：

| dataset_id | field | quality_status | observations |
| --- | --- | --- | --- |
| index_daily | close | BLOCKED_UNRESOLVED_CROSS_SOURCE_CONFLICT | 2 |
| index_daily | low | BLOCKED_UNRESOLVED_CROSS_SOURCE_CONFLICT | 1 |
| stock_adjustment | adj_factor | BLOCKED_OUTSIDE_REGISTERED_IDENTITY_INTERVAL | 20062 |
| stock_adjustment | adj_factor | BLOCKED_UNRESOLVED_ACTION_BASIS | 4 |
| stock_adjustment | adj_factor | QUALIFIED_FACTOR_PRECISION | 3062 |
| stock_adjustment | adj_factor | VERIFIED_SPECIAL_RETURN_BASIS | 2 |
| stock_daily_basic | circ_mv | BLOCKED_MISSING_REQUIRED_FIELD | 11 |
| stock_daily_basic | circ_mv | BLOCKED_UNRESOLVED_SHARE_DENOMINATOR | 1367 |
| stock_daily_basic | circ_mv | QUALIFIED_EMPIRICAL_SHARE_PRECISION | 237371 |
| stock_daily_basic | close | STRUCTURAL_SUSPENSION_NO_TRADE | 11 |
| stock_daily_basic | pb | BLOCKED_MISSING_REQUIRED_FIELD | 75315 |
| stock_daily_basic | pe | UNDEFINED_OR_UNAVAILABLE_PE | 1764344 |
| stock_daily_basic | pe_ttm | UNDEFINED_OR_UNAVAILABLE_PE | 2208525 |
| stock_daily_basic | total_mv | BLOCKED_MISSING_REQUIRED_FIELD | 11 |
| stock_daily_basic | total_mv | BLOCKED_UNRESOLVED_SHARE_DENOMINATOR | 613 |
| stock_daily_basic | total_mv | QUALIFIED_EMPIRICAL_SHARE_PRECISION | 223589 |
| stock_daily_basic | turnover_rate | BLOCKED_UNRESOLVED_SHARE_DENOMINATOR | 360 |
| stock_daily_basic | turnover_rate | STRUCTURAL_SUSPENSION_NO_TRADE | 11 |
| stock_daily_basic | turnover_rate_f | BLOCKED_MISSING_REQUIRED_FIELD | 39 |
| stock_daily_basic | turnover_rate_f | BLOCKED_UNRESOLVED_SHARE_DENOMINATOR | 500 |
| stock_daily_basic | turnover_rate_f | STRUCTURAL_SUSPENSION_NO_TRADE | 11 |
| stock_limits | down_limit | SPECIAL_IPO_AUCTION_REGIME | 48 |
| stock_limits | down_limit | STRUCTURAL_NO_DAILY_PRICE_LIMIT | 22 |
| stock_limits | up_limit | SPECIAL_IPO_AUCTION_REGIME | 48 |
| stock_limits | up_limit | STRUCTURAL_NO_DAILY_PRICE_LIMIT | 22 |
| stock_moneyflow | net_mf_amount | BLOCKED_FLOW_WITHOUT_OBSERVED_TRADE | 82 |
| stock_moneyflow | net_mf_vol | BLOCKED_FLOW_WITHOUT_OBSERVED_TRADE | 82 |

涨跌停及资金流逐证券—交易日复核：

| dataset_id | year | status | observations |
| --- | --- | --- | --- |
| stock_limits | 2014 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 569894 |
| stock_limits | 2014 | VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT | 54 |
| stock_limits | 2015 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 569694 |
| stock_limits | 2015 | VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT | 4 |
| stock_limits | 2016 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 641546 |
| stock_limits | 2017 | VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT | 4 |
| stock_limits | 2017 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 743235 |
| stock_limits | 2018 | VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT | 3 |
| stock_limits | 2018 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 816985 |
| stock_limits | 2019 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 884862 |
| stock_limits | 2019 | VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT | 5 |
| stock_limits | 2020 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 945962 |
| stock_limits | 2021 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 1058863 |
| stock_limits | 2022 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 1146263 |
| stock_limits | 2023 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 1209468 |
| stock_limits | 2024 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 1233202 |
| stock_limits | 2025 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 1248108 |
| stock_limits | 2026 | BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION | 913218 |
| stock_moneyflow | 2014 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 569948 |
| stock_moneyflow | 2015 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 569698 |
| stock_moneyflow | 2016 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 640716 |
| stock_moneyflow | 2016 | MISSING_SOURCE_ROW | 830 |
| stock_moneyflow | 2017 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 741872 |
| stock_moneyflow | 2017 | MISSING_SOURCE_ROW | 1367 |
| stock_moneyflow | 2018 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 816690 |
| stock_moneyflow | 2018 | MISSING_SOURCE_ROW | 298 |
| stock_moneyflow | 2019 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 884844 |
| stock_moneyflow | 2019 | MISSING_SOURCE_ROW | 23 |
| stock_moneyflow | 2020 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 945946 |
| stock_moneyflow | 2020 | MISSING_SOURCE_ROW | 16 |
| stock_moneyflow | 2021 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 1058846 |
| stock_moneyflow | 2021 | MISSING_SOURCE_ROW | 17 |
| stock_moneyflow | 2022 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 1146263 |
| stock_moneyflow | 2023 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 1209461 |
| stock_moneyflow | 2023 | MISSING_SOURCE_ROW | 7 |
| stock_moneyflow | 2024 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 1233202 |
| stock_moneyflow | 2025 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 1248108 |
| stock_moneyflow | 2026 | SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED | 913218 |

48个原始公告证实的区间关闭11882条缺行情问题，未添加任何虚构价格或零收益。跨代码别名被归并到历史证券身份，保留源代码及证据。证券目录保留333只退市证券；对已出现代码的覆盖通过，但历史上市目录的独立穷尽认证仍未完成。

7条 daily_basic 收盘价错误经独立未复权报价核正，依赖市值/换手可透明重算，无法核实的估值分母字段隔离。复权侧重取76个证券的完整一致版本，更新7826个因子值；另按原公告修复000545在2015-03-26遗漏的10转3，影响2797条后续因子。全量剩余差异按量化精度、股改特殊口径和未决事项分开，未把它们自动认证。

五维支持：趋势、波动压力和下行损失具备七指数5/20/60日连续指标；活跃度/流动性具备成交、换手原始池和Amihud代理；结构具备历史全A股涨跌广度、未报价比例及60日完整交易面板平均相关。流动性与结构仍是明确条件的代理层，不能与精确指数成分指标混称正式认证。未报价比例不等于停牌比例；停牌终止公告的事后信息未进入历史特征。

资金流补入570076条此前缺失的提供商记录；对所有后续缺口证券范围重新请求后，仍有2558个已交易日未返回资金流记录，保留真实缺口，不填零。66条涨跌停异常通过48家IPO原始公告及股改/恢复上市/吸收合并公告核实，形成70个特殊规则日期（包括天宜上佳上市前五个交易日）。普通日涨跌停字段留空，保留原提供商值及规则证据；新股分时竞价申报范围单独说明，不冒充普通固定日涨跌停。

历史成分：399001重建38次公告、39个500成员组合、19500条有效期记录；其他六指数未获得完整有效成分历史。现有576892行权重保留快照语义，不向前铺满月份。

主要证据：`audit/final_data_foundation/market_coverage/`、`source_reconciliation/`、`issue_closure/issues.parquet`。
反向核查发现82条资金流记录没有对应行情，停牌资料将这些证券日期标记为停牌；重新请求六个日期后全部仍存在。两个必需资金流字段共164项已隔离，来源矛盾保持OPEN，不能视为正常交易日资金流。深圳市场汇总股本也不再套用个股万股单位，未获证实的源单位明确标记。

