# 需手工下载的数据与页面 (manual_sources.md)

生成于 2026-11-12。以下项目在自动化环境中未能取到，给出可直接访问的官方页面。

| 序列 | 内容 | 官方页面 | 链接 | 备注 |
|---|---|---|---|---|
| `cgb_1y / cgb_10y` | 1年期、10年期国债到期收益率（日） | 中国债券信息网「中债国债收益率曲线」 | [打开](https://yield.chinabond.com.cn/cbweb-mn/yield_main?locale=zh_CN) | 页面按日期查询并导出；或用中国货币网收益率曲线页 https://www.chinamoney.com.cn/chinese/bkcurvfx/ 。需逐日或按月导出，注意国债收益率曲线只在银行间交易日发布。 |
| `usdcny_fixing` | 美元兑人民币中间价（日） | 中国货币网「人民币汇率中间价」 | [打开](https://www.chinamoney.com.cn/chinese/bkccpr/) | 官方另有国家外汇管理局「人民币汇率中间价」页 https://www.safe.gov.cn/safe/rmbhlzjj/index.html 。中间价每交易日 9:15 发布，须记录交易日期而非月末。 |
| `dr007` | 存款类机构质押式回购7天加权利率（日） | 中国货币网「银行间质押式回购」 | [打开](https://www.chinamoney.com.cn/chinese/bkfrr/) | 该接口在本环境仅返回利率期限结构表，未暴露 DR007 时间序列；页面可查历史并导出。 |
| `fai_ytd_yoy` | 固定资产投资累计同比（月） | 国家统计局「固定资产投资」月度发布 | [打开](https://www.stats.gov.cn/sj/zxfb/) | 标题不含数值，需读正文；1—2月合并发布，注意春节错月。 |
| `core_cpi_yoy` | 核心CPI同比（月） | 国家统计局 CPI 发布正文/数据表 | [打开](https://www.stats.gov.cn/sj/zxfb/) | 核心CPI 在正文中单独给出（扣除食品和能源），标题不含。 |
| `tsf_stock_yoy 长历史 / tsf_flow` | 社融存量同比、社融增量（月） | 中国人民银行「社会融资规模」统计表 | [打开](https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html) | 央行列表页不分页（index_1.html 返回 404），仅能取近14期；长历史需从年度统计表下载。 |
| `loan_balance_yoy` | 人民币贷款余额同比（月） | 中国人民银行「金融机构信贷收支表」 | [打开](https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html) | 同上，需年度归档页。 |
| `fx_reserves` | 外汇储备（月，亿美元） | 国家外汇管理局「外汇储备」 | [打开](https://www.safe.gov.cn/safe/whcb/index.html) | 月度发布，含汇率折算与估值效应说明。 |

## 下载建议

1. 日频利率/汇率务必记录**交易日期**，不要用「所属月最后一天」代替。
2. 导出后保留原始文件与下载时间，便于追溯 `vintage_date`。
3. 若页面支持按日期区间导出，建议区间从 2015-01-01 起，与现有序列对齐。