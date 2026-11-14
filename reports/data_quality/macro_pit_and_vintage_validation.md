# 历史可得性与版本验证

本轮仅做数据工程。市场协议 market-research-v2.0.0、阈值、状态、标签、599 个周度样本与原时间折保持冻结；未运行模型、调参或预测实验。

| quality_status                     |   记录数 |   指标数 |
|:-----------------------------------|---------:|---------:|
| blocked                            |      313 |        4 |
| conservative_release_reconstructed |    22252 |       26 |
| latest_vintage_reconstructed       |    15338 |       33 |
| strict_pit_eligible                |     4883 |       47 |

strict为具日期的官方公告值；conservative含官方历史报价、同期转载和具日期官方重刊；latest为仅现行历史汇编或附件版本不明；blocked为口径未通过。四类都保留原始来源。未认证不等于缺数，真实PIT不等于简单按月平移。

2022Q3 GDP实际公告2022-10-24，PMI可能月末前发布；2025-02-14日终M2不得进入当日18:00样本。实际历史截断及未来值扰动检查见validation_results.json，逐单元格检查见lineage_validation.json。不存在所有历史修订均已取得的声明。
