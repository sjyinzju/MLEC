# 宏观语义验证

本轮仅做数据工程。市场协议 market-research-v2.0.0、阈值、状态、标签、599 个周度样本与原时间折保持冻结；未运行模型、调参或预测实验。

已修正或重新验证：GDP单季/累计、工业和零售当月/累计及负号、人民币贷款当月/累计与社融分项、M1新旧、贸易币种、外储USD/SDR、LPR参数与频率、DR007字段和收益率同源期限利差。新增5条旧零售候选可得日期继承错误已清除，证据见legacy_availability_corrections.json。

每个准入指标的unit/currency/frequency/measure_type与声明一致；检查结果见semantic_validation.json。社融四次主要扩围已分列独立序列，跨范围变化不再生成；范围不明的旧汇编单列候选。尚未构造恒定范围面板，统计制度的其他调整仍需逐公告脚注解释，G3保留QUALIFIED。
