# 中国宏观数据包（首轮）

构建时间：2026-11-12 | 记录 12,417 行 | 序列 19 个

## 文件

| 文件 | 内容 |
|---|---|
| `macro_raw.parquet` | 长表原始数据，含发布时点与质量标记 |
| `macro_raw.csv` | 同上，CSV 备份 |
| `macro_metadata.csv` | 序列级元数据与覆盖统计 |
| `macro_release_calendar.csv` | 发布日历（官方观测 + 保守推断） |
| `macro_data_quality.md` | 质量报告、口径说明、缺口 |
| `manual_sources.md` | 需手工下载的项目与链接 |
| `crosscheck_official_vs_eastmoney.csv` | 官方 vs 第三方核验 |

## 数据获取脚本

```
scripts/lib_common.py       公共抓取工具
scripts/collect_nbs_list.py 统计局发布列表（标题+日期）
scripts/collect_nbs.py      统计局序列（标题解析+正文兜底）
scripts/collect_pboc.py     央行货币信用（M2/社融/贷款）
scripts/collect_cm.py       货币网利率（Shibor/DR/LPR）
scripts/collect_em.py       东方财富长历史回填
scripts/build_package.py    合并、赋发布时点、导出交付包
scripts/make_docs.py        生成质量报告与说明
```

复现顺序：

```powershell
python scripts/collect_nbs_list.py
python scripts/collect_nbs.py
python scripts/collect_pboc.py
python scripts/collect_cm.py
python scripts/collect_em.py
python scripts/build_package.py
python scripts/make_docs.py
```

## 使用要点

- 回测筛选一律用 `available_at`，不要用 `period_end`。
- 关注 `quality_flag`：`official` 可直接用；`backfill_third_party_assumed_release` 的发布日为保守推断。
- `measure_type` 区分 yoy / mom / ytd_yoy / flow / level，勿混用。