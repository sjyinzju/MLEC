# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

市场契约：`config/data/market_requirements.json`；宏观契约：`config/data/macro_requirements.json`；统一矩阵：`data/metadata/research_data_requirements.parquet`。必需与可选依据经济研究用途和冻结协议确定，未因缺数删除变量。

观察期、市场交易日、公告时间、实际版本可得时间、下载时间和成分生效时间分别保存。只有 `research_available_at <= asof_time` 的许可版本可进入对应视图。`quote_reconstructed` 对 DR007 明确使用另存的历史收盘可得假设；其真实版本可得时间仍保留，不能称为严格PIT。市场 v2 和 v4 连续扩展均明确为历史报价重建。

公告日期未知时不得由 URL 年份、文件名或观测月猜测。官方后期年报只能在年报发布日期后使用；同一时刻上载的海关月报按已证明的刊期顺序保存。LPR 月末是归档月份，实际定盘在 `observation_date`；春节前发布的 PMI 按原公告日期使用。

价格为未复权原始报价；复权因子另列并保留修复前值。指数为价格指数，不含现金分红再投资。股票成交额由千元转为元，成交量由手转为股；指数daily_basic市值原单位为元、股本为股，不能套用个股daily_basic万元/万股单位。实际字段定义由保存的供应商说明与 `field_dictionary.parquet` 绑定。

结构性缺失须有制度/上市/日历证据。真实缺失、过期、未认证、冲突、结构性不适用分别保留。停牌不填零收益。未知未来成分和事后停牌终止日不进入过去特征。
