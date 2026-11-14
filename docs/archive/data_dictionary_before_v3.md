# 研究数据字典

## 数据集及主键

| 权威路径 | 角色 / 键 |
|---|---|
| data/raw/macro/original_submissions/v1 | 原交付字节快照，包含原数据、元数据、旧报告 |
| data/raw/macro/original_submissions/peer_scripts | 相邻目录找到的八个同伴脚本，原样留存 |
| data/raw/macro/official_sources | 公告正文、官方索引日期、金融报价原响应 |
| data/raw/macro/third_party_sources | 本地 QuantData 只读提取与公开历史响应 |
| data/standardized/macro/macro_facts.parquet | 一条指标、统计期间、版本、来源事实 |
| data/standardized/macro/macro_vintages.parquet | 同事实版本键对应原值和修订状态 |
| data/standardized/macro/macro_release_events.parquet | 同版本键对应发布日期与研究可得时间 |
| data/metadata/data_lineage.parquet | 来源 URL、原值、证据路径和转换说明 |
| data/features/macro_weekly.parquet | sample_id 唯一，周度宏观宽表 |
| data/features/macro_availability.parquet | sample_id + series_id；输入证据 ID、可得时间、缺失原因 |
| data/datasets/main_v1 | 样本、市场/宏观特征、目标分别储存 |
| data/datasets/common_*_v1/common_samples.parquet | 各宏观组的共同样本资格，M 与 M+Z 同时使用 |

事实自然键为 `(series_id, period_start, period_end)`，版本键追加 `(vintage_id, source_record_id)`。自然键可有多个合法修订；版本键不得重复。同一版本时间存在不同可信值时验收失败，不能凭行顺序选择。

## 事实字段

| 字段 | 含义 |
|---|---|
| series_id / series_name / series_group | 唯一经济口径及经济分组 |
| value / unit / currency | 原口径数值、单位、币种；百分数保留 2.0 表示 2%，不转为 0.02 |
| frequency / measure_type | D/M/Q；level/yoy/mom/ytd_yoy/flow/ytd_flow/stock |
| period_start / period_end / observation_date | 经济统计期间；日频保留报价原日期 |
| release_at | 官方公告日期的日末或报价日的日末；未知则缺失 |
| research_available_at | 实际准入时间；未知历史版本以获取时间限制，不回填 |
| release_time_basis | 发布时间证据或保守规则 |
| retrieved_at | 此次获取时间，不是历史发布日期 |
| vintage_id / revision_status | 公告或档案版本；不以下载年份假装初次值 |
| source_name / source_url / source_record_id | 可追踪来源与稳定记录身份 |
| value_quality / time_quality / vintage_quality / quality_status | 数值、时间、版本、准入等级分别记录 |
| adjustment_note / evidence_path | 转换理由、可核对的原始文件 |
| original_series_id / original_value / claimed_available_at | 原交付主张保留，修复可追溯 |

全部可得时间是 Asia/Shanghai 时区。统计期间为无时区的日期。GDP 季度与累计同比、工业/零售当月与累计同比、贷款单月与累计流量使用不同序列。M1 在 2025 年新定义另列 `m1_new_yoy`。国债曲线是 CFETS 11:30 报价均值；汇率 `usdcny_fixing` 是 CNY/USD，来源为 SAFE 每 100 美元折人民币，除以 100。

每条序列的单位、起止期间、缺口、质量状态见 `data/metadata/macro_feature_catalog.csv` 和 `macro_acceptance_catalog.csv`；所有原始文件哈希见 `raw_source_registry.json`。

## 样本与目标

`sample_id/asof_date/asof_time/horizon/risk_set/target_valid/label_available_at` 直接复用冻结市场表。预测时点为完整 SSE 交易周最后开放日 18:00。目标 `y_new_episode_next20`；训练标签须在 fit_cutoff 前成熟。2023+ 新建标签表为空，原市场文件不改动。市场特征只允许冻结白名单 25 项；未来风险观测、事件 ID、目标有效性等只作元数据，不入 X。

宏观派生列命名 `z__<series>__latest/previous/change/age_days`；日频另有 `mean_5d/mean_20d`。先在统计期间内按可得时间选版本，再选最新统计期间；报价均值使用最近已知报价时点之前的 5/20 个 SSE 开放日，窗口不完整则缺失。禁止向后填充。
