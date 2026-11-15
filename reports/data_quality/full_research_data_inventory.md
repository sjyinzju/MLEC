# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

| dataset_id | domain | authority_path | rows | quality_status |
| --- | --- | --- | --- | --- |
| index_daily | M | data/standardized/market/v4/index_daily/*.parquet | 21665 | FAIL |
| index_daily_basic | M | data/standardized/market/v4/index_daily_basic/*.parquet | 21474 | QUALIFIED |
| stock_daily | M | data/standardized/market/v4/stock_daily_observations/*.parquet | 11981370 | QUALIFIED |
| stock_daily_basic | M | data/standardized/market/v4/stock_daily_basic_observations/*.parquet | 11981381 | FAIL |
| stock_adjustment | M | data/standardized/market/v4/stock_adjustment_observations/*.parquet | 12333672 | FAIL |
| stock_master_history | M | data/standardized/market/v4/stock_master_history.parquet | 5559 | QUALIFIED |
| stock_name_history | M | data/standardized/market/v4/stock_name_history/*.parquet | 13851 | QUALIFIED |
| stock_trading_status | M | data/standardized/market/v4/stock_trading_status/*.parquet | 12313921 | QUALIFIED |
| index_constituents_history | M | data/standardized/market/v4/index_constituents_history.parquet | 19500 | FAIL |
| index_weights_history | M | data/standardized/market/v4/index_weights_history/*.parquet | 576892 | QUALIFIED |
| trade_calendar | M | data/standardized/market/v4/trade_calendar/*.parquet | 9386 | QUALIFIED |
| index_identity | M | data/standardized/market/v4/index_identity/*.parquet | 7 | QUALIFIED |
| stock_limits | M | data/standardized/market/v4/stock_limits_observations/*.parquet | 12309435 | QUALIFIED |
| margin_market | M | data/standardized/market/v4/margin_market/*.parquet | 6579 | QUALIFIED |
| margin_security | M | data/standardized/market/v4/margin_security/*.parquet | 5751345 | QUALIFIED |
| stock_moneyflow | M | data/standardized/market/v4/stock_moneyflow/*.parquet | 11978894 | FAIL |
| exchange_activity_sh | M | data/standardized/market/v4/exchange_activity_sh/*.parquet | 55398 | QUALIFIED |
| exchange_activity_sz | M | data/standardized/market/v4/exchange_activity_sz/*.parquet | 41454 | QUALIFIED |
| stock_connect_top10 | M | data/standardized/market/v4/stock_connect_top10/*.parquet | 50010 | QUALIFIED |
| stock_dividend_events | M | data/standardized/market/v4/stock_dividend_events/*.parquet | 212115 | QUALIFIED |
| market_data_quality | M | data/standardized/market/v4/market_data_quality.parquet | 4535515 | QUALIFIED |
| macro_facts | Z | data/standardized/macro/v4/macro_facts.parquet | 47603 | FAIL |
| macro_vintages | Z | data/standardized/macro/v4/macro_vintages.parquet | 47603 | QUALIFIED |
| macro_release_events | Z | data/standardized/macro/v4/macro_release_events.parquet | 47603 | QUALIFIED |
| macro_quality | Z | data/standardized/macro/v4/macro_quality.parquet | 47603 | QUALIFIED |

外部目录分域：

| source_dataset | scope | registered_rows | reason |
| --- | --- | --- | --- |
| adj_factor | REQUIRED | 12428062 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| balancesheet | OUT_OF_SCOPE | 317073 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| block_trade | CANDIDATE | 562051 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| bse_mapping | CANDIDATE | 496 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cashflow | OUT_OF_SCOPE | 315612 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| cn_cpi | CANDIDATE | 141 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cn_gdp | CANDIDATE | 46 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cn_m | CANDIDATE | 141 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cn_pmi | CANDIDATE | 142 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cn_ppi | CANDIDATE | 141 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| cn_schedule | CANDIDATE | 159 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| daily | REQUIRED | 11914518 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| daily_basic | REQUIRED | 11824246 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| daily_info | CANDIDATE | 55720 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| disclosure_date | OUT_OF_SCOPE | 300415 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| dividend | CANDIDATE | 212987 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| etf_limit | OUT_OF_SCOPE | 2293124 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| express | OUT_OF_SCOPE | 20609 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fina_audit | OUT_OF_SCOPE | 63516 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fina_indicator | OUT_OF_SCOPE | 389530 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fina_mainbz | OUT_OF_SCOPE | 1780812 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| forecast | OUT_OF_SCOPE | 83958 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_adj | OUT_OF_SCOPE | 3016390 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_basic | OUT_OF_SCOPE | 5824 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_daily | OUT_OF_SCOPE | 2827513 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_div | OUT_OF_SCOPE | 4083 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_nav | OUT_OF_SCOPE | 3040262 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| fund_share | OUT_OF_SCOPE | 2058878 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| gz_index | CANDIDATE | 644 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| hsgt_top10 | CANDIDATE | 50550 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| income | OUT_OF_SCOPE | 304380 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| index_basic | REQUIRED | 21208 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| index_classify | CANDIDATE | 1740 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| index_daily | REQUIRED | 23785592 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| index_dailybasic | REQUIRED | 41293 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| index_member_all | CANDIDATE | 7943 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| index_weight | REQUIRED | 864616 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| margin | CANDIDATE | 6660 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| margin_detail | CANDIDATE | 6556733 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| margin_secs | CANDIDATE | 7978603 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| moneyflow | CANDIDATE | 11571464 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| namechange | REQUIRED | 14226 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| new_share | CANDIDATE | 3275 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| pledge_detail | OUT_OF_SCOPE | 220409 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| pledge_stat | OUT_OF_SCOPE | 1647811 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| repurchase | OUT_OF_SCOPE | 63587 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| sf_month | CANDIDATE | 141 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| share_float | OUT_OF_SCOPE | 6303604 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| shibor | CANDIDATE | 2932 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| shibor_lpr | CANDIDATE | 365 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| shibor_quote | CANDIDATE | 5830 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| stk_holdernumber | OUT_OF_SCOPE | 473196 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| stk_holdertrade | OUT_OF_SCOPE | 162160 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| stk_limit | CANDIDATE | 12198498 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| stk_managers | OUT_OF_SCOPE | 363487 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| stk_rewards | OUT_OF_SCOPE | 1645115 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| stk_seasoned | OUT_OF_SCOPE | 9825 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| stock_basic | REQUIRED | 11814 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| stock_company | OUT_OF_SCOPE | 12588 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| suspend_d | REQUIRED | 334892 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| sz_daily_info | CANDIDATE | 41832 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| top10_floatholders | OUT_OF_SCOPE | 2098029 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| top10_holders | OUT_OF_SCOPE | 2319216 | Firm accounting, ownership/governance or fund-level data; not an input to the defined broad equity market five dimensions or macro information set |
| top_inst | CANDIDATE | 2407943 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| top_list | CANDIDATE | 200470 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |
| trade_cal | REQUIRED | 10280 | Market identity, coverage, adjustment, index structure or mandatory market measurements |
| wz_index | CANDIDATE | 2730 | Documented market structure/liquidity/cross-market or macro extension; retain and inspect availability |

