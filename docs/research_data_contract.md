# 研究数据契约

当前版本 practical-research-data-v5。市场与宏观需求见 config/data/{market,macro}_requirements.json；必需/可选分类不因缺数而改变。每个正式表只有一个注册权威路径。

观察期间、交易日、实际公告、版本可得时间、采集时间和成分生效时间分别保存。historical_reconstructed 接受可信历史值及明确的保守可得时间；third_party_historical_quote 仅在存在 reconstructed_quote_at 时使用该显式时钟。可得时间必须不晚于预测时点。不能把后期回溯发布提前用于以前的周。没有未来回填、零收益补缺、全样本插补或任何模型拟合。

同年同口径月流量可求和形成累计；单位、币种和范围必须一致，时间取父记录最晚可得时间。统计范围改变时 previous/change 重置，不跨制度拼接。

股票价格为未复权报价，复权因子独立列出；指数为价格指数。标准 amount_cny/volume_shares 为元/股，源 amount/vol 仍保留其字典规定的单位。指数 daily_basic 市值/股本为元/股，个股 daily_basic 为万元/万股。深交所股票类别金额为元、数量为股，其他类别数量未认证。

来源冲突、真实缺数、过期、制度性不适用分别保留。PE 源空值不能全部视为亏损的结构性缺失。PB 非正净资产标记有实际披露依据。质量筛选依赖 market_data_quality 和宏观 certification_status；非空值不是自动认证。

load_dataset 返回全部 599 个候选时点及显式 eligibility。H5/H20/H40 标签、风险集和时间折冻结。精确逐日成分未知时必须明确使用 monthly_snapshot；当前成分不得回填历史。
