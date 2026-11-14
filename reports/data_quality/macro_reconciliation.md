# 宏观语义修复与交叉核对

同伴八个采集脚本已在相邻 scripts 目录找到并按哈希归档；不再将其列为缺失。原包保留于 `data/raw/macro/original_submissions/v1/`。新版采集器补齐分页，并以缓存公告正文和官方列表日期为证据。

- 工业、零售的当月同比与累计同比分别建序列；2022-04 工业当月 -2.9%、累计 4.0%，不混用。下降/负值照原文保留。
- 贷款单月增量和年初累计分开，仅采明确单月陈述；不能识别的原记录保留 blocked。
- PMI 新订单映射 `pmi010500`，`pmi010200` 是中型企业 PMI。早期跨月发布和 2022-01 月末前发布保留真实日期。
- GDP 当季同比与累计同比分开；后续公告中的历史季度修订保留该次公告时间，不能提前使用。
- CPI/PPI 环比、同比依据表头顺序解析；核心 CPI 使用不包括食品和能源行。M1 的 2025 年新定义独立为 `m1_new_yoy`。
- SAFE 美元中间价原单位为每 100 美元折人民币，除以 100 得 CNY/USD。国债收益率是 CFETS 11:30 均值曲线，不能称中债收盘收益率。

| series_id             |   overlap |   differences |
|:----------------------|----------:|--------------:|
| cpi_mom               |       140 |             0 |
| cpi_yoy               |       140 |             0 |
| industrial_va_yoy     |       127 |             0 |
| industrial_va_ytd_yoy |       134 |             0 |
| m1_yoy                |       120 |             2 |
| m2_yoy                |       139 |            11 |
| new_rmb_loans         |       121 |           107 |
| pmi_mfg               |       141 |             0 |
| pmi_new_orders        |       141 |             0 |
| pmi_nonmfg            |       141 |             0 |
| ppi_mom               |       140 |             0 |
| ppi_yoy               |       140 |             0 |
| retail_sales_yoy      |       127 |             0 |
| retail_sales_ytd_yoy  |       140 |             0 |

交叉核对使用本地 QuantData 提取的事后历史表。价格和 PMI 的一致仅验证字段/数值，不证明发布版本。M2 等差异保留官方当时公告值，不用后来历史值覆盖；差异逐行保存于 `audit/framework/macro_crosscheck.parquet`。极端跳变只列入复核表，不截尾真实疫情冲击。原修复对应表 `audit/framework/macro_corrections.parquet`，全链路 `data/metadata/data_lineage.parquet`。
