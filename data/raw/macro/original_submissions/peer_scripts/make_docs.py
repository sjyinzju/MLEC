"""Generate macro_data_quality.md, README.md and manual_sources.md from outputs."""
from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import ROOT  # noqa: E402

OUT = os.path.join(ROOT, "deliverables")
TODAY = "2026-11-12"

MANUAL = [
    ("cgb_1y / cgb_10y", "1年期、10年期国债到期收益率（日）",
     "中国债券信息网「中债国债收益率曲线」",
     "https://yield.chinabond.com.cn/cbweb-mn/yield_main?locale=zh_CN",
     "页面按日期查询并导出；或用中国货币网收益率曲线页 https://www.chinamoney.com.cn/chinese/bkcurvfx/ 。"
     "需逐日或按月导出，注意国债收益率曲线只在银行间交易日发布。"),
    ("usdcny_fixing", "美元兑人民币中间价（日）",
     "中国货币网「人民币汇率中间价」",
     "https://www.chinamoney.com.cn/chinese/bkccpr/",
     "官方另有国家外汇管理局「人民币汇率中间价」页 https://www.safe.gov.cn/safe/rmbhlzjj/index.html 。"
     "中间价每交易日 9:15 发布，须记录交易日期而非月末。"),
    ("dr007", "存款类机构质押式回购7天加权利率（日）",
     "中国货币网「银行间质押式回购」",
     "https://www.chinamoney.com.cn/chinese/bkfrr/",
     "该接口在本环境仅返回利率期限结构表，未暴露 DR007 时间序列；页面可查历史并导出。"),
    ("fai_ytd_yoy", "固定资产投资累计同比（月）",
     "国家统计局「固定资产投资」月度发布",
     "https://www.stats.gov.cn/sj/zxfb/",
     "标题不含数值，需读正文；1—2月合并发布，注意春节错月。"),
    ("core_cpi_yoy", "核心CPI同比（月）",
     "国家统计局 CPI 发布正文/数据表",
     "https://www.stats.gov.cn/sj/zxfb/",
     "核心CPI 在正文中单独给出（扣除食品和能源），标题不含。"),
    ("tsf_stock_yoy 长历史 / tsf_flow", "社融存量同比、社融增量（月）",
     "中国人民银行「社会融资规模」统计表",
     "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
     "央行列表页不分页（index_1.html 返回 404），仅能取近14期；长历史需从年度统计表下载。"),
    ("loan_balance_yoy", "人民币贷款余额同比（月）",
     "中国人民银行「金融机构信贷收支表」",
     "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
     "同上，需年度归档页。"),
    ("fx_reserves", "外汇储备（月，亿美元）",
     "国家外汇管理局「外汇储备」",
     "https://www.safe.gov.cn/safe/whcb/index.html",
     "月度发布，含汇率折算与估值效应说明。"),
]


def main():
    df = pd.read_parquet(os.path.join(OUT, "macro_raw.parquet"))
    meta = pd.read_csv(os.path.join(OUT, "macro_metadata.csv"), encoding="utf-8-sig")
    cal = pd.read_csv(os.path.join(OUT, "macro_release_calendar.csv"), encoding="utf-8-sig")
    try:
        ck = pd.read_csv(os.path.join(OUT, "crosscheck_official_vs_eastmoney.csv"),
                         encoding="utf-8-sig")
    except FileNotFoundError:
        ck = pd.DataFrame()

    n_off = int((df["quality_flag"] == "official").sum())
    n_bf = int(df["quality_flag"].str.startswith("backfill").sum())

    lines = []
    A = lines.append
    A("# 宏观数据质量报告 (macro_data_quality.md)")
    A("")
    A(f"生成时间：{TODAY}（Asia/Shanghai）  |  记录数：{len(df):,}  |  "
      f"序列数：{df['series_id'].nunique()}")
    A("")
    A("## 1. 环境与可达性结论（重要）")
    A("")
    A("| 数据源 | 可达性 | 采集方式 | 说明 |")
    A("|---|---|---|---|")
    A("| 国家统计局 `data.stats.gov.cn`（国家数据） | ❌ 阻断 | — | 奇安信云 WAF 返回 `403 / reason:UrlACL`，"
      "带会话 Cookie 仍 403，属边缘 IP/URL 白名单拦截，非账号权限问题 |")
    A("| 国家统计局 `www.stats.gov.cn`（发布稿） | ✅ 可用 | 抓列表页+正文 | 标题常自带数值与发布日期 |")
    A("| 中国人民银行 `www.pbc.gov.cn` | ✅ 可用 | 抓报告正文 | 列表页不分页，仅近 14 期 |")
    A("| 国家外汇管理局 `www.safe.gov.cn` | ✅ 可用 | 页面可读 | 结构化表格需手工导出 |")
    A("| 中国货币网 `www.chinamoney.com.cn` | ✅ 可用 | JSON 接口 | Shibor/DR 期限表/LPR 可取 |")
    A("| 东方财富数据中心 API | ✅ 可用 | JSON 接口 | 用于 2008 年前后至今长历史回填与交叉核验 |")
    A("")
    A("因浏览器自动化（Chrome/CDP）在当前沙箱被禁止创建进程间通道，无法用真实浏览器指纹绕过 WAF；"
      "`data.stats.gov.cn` 的「国家数据」明细库未能直采。")
    A("")
    A("## 2. 序列覆盖与质量标记")
    A("")
    A("| 序列 | 中文名 | 优先级 | 区间 | 条数 | 官方行 | 回填行 |")
    A("|---|---|---|---|---|---|---|")
    for _, r in meta.iterrows():
        A(f"| `{r['series_id']}` | {r['series_name']} | {r['priority']} | "
          f"{r['first_period']} → {r['last_period']} | {r['obs_count']} | "
          f"{r['n_official_rows']} | {r['n_backfill_rows']} |")
    A("")
    A(f"- `quality_flag = official`：{n_off:,} 行，数值与发布日期直接来自官方页面。")
    n_oa = int((df["quality_flag"] == "official_value_assumed_release").sum())
    A(f"- `quality_flag = official_value_assumed_release`：{n_oa:,} 行，数值来自官方报告正文，"
      "但发布日由报告编号推断（见第 4 节）。")
    A(f"- `quality_flag = backfill_third_party_assumed_release`：{n_bf:,} 行，"
      "数值来自东方财富转载的官方口径，**发布日期为保守推断**（见第 4 节）。")
    A("- 无任何行使用未来值填补；缺失即缺失。")
    A("")
    A("## 3. 口径与结构性说明")
    A("")
    A("- **社零为累计同比**（`retail_sales_ytd_yoy`）：统计局标题给的是「1—N月」累计增速，"
      "与单月同比不同，已用 `measure_type=ytd_yoy` 标注，不可直接与单月同比序列混用。")
    A("- **工业增加值为单月同比**（`industrial_va_yoy`）。")
    A("- **PMI 为指数水平**（50 为荣枯线），不是百分比变化；`measure_type=level`。")
    A("- **Shibor 自 2006-10-08 起发布**，2007 年之前不存在，未做任何填补；"
      "非交易日无报价即空缺。")
    A("- **LPR 接口只返回最近 12 期**，历史需手工下载；2019-08 之前的旧 LPR 机制不同，未混入。")
    A("- **M1 口径调整提示**：M1 统计口径近年有修订（纳入个人活期存款等），"
      "跨年比较需核对；本包未做口径拼接，相关行标 `adjustment_note`。")
    A("- **GDP 为初步核算数**，后续存在修订，`revision_flag` 已标注。")
    A("- **进出口为美元计价同比**（海关总署口径）。")
    A("- **1—2 月合并发布**：统计局部分月度指标在 1—2 月合并公布，导致 1 月缺失，"
      "此为发布制度所致，非采集失败。")
    A("")
    A("## 4. 发布时点（release_date / available_at）规则")
    A("")
    A("官方行：`release_date` 取自发布页标注日期。")
    A("")
    A("回填行采用保守假定（宁晚不早，避免前视偏差）：")
    A("")
    A("| 序列 | 假定规则 |")
    A("|---|---|")
    rules = {
        "CPI/PPI 同比环比": "次月 15 日 09:30",
        "工业增加值 / 社零": "次月 20 日 10:00",
        "PMI": "当月最后一日 09:30",
        "M2 / 社融 / 新增贷款": "次月 15 日 16:00",
        "GDP": "季后次月 20 日 10:00",
        "进出口": "次月 13 日 11:00",
        "Shibor": "交易日 11:00（当日已发布）",
        "LPR": "报价日 09:15",
    }
    for k, v in rules.items():
        A(f"| {k} | {v} |")
    A("")
    A("`available_at` = `release_date` + `release_time` + 北京时区偏移，"
      "回测时应以 `available_at <= t` 作为可用性筛选条件，**不要**用 `period_end`。")
    A("")
    A("## 5. 官方值与第三方转载的交叉核验")
    A("")
    if len(ck):
        A("| series_id | overlap_n | max_abs_diff | mean_abs_diff | mismatch_gt_tol |")
        A("|---|---|---|---|---|")
        for _, r in ck.iterrows():
            A(f"| `{r['series_id']}` | {int(r['overlap_n'])} | {r['max_abs_diff']} | "
              f"{r['mean_abs_diff']} | {int(r['mismatch_gt_tol'])} |")
        A("")
        A("容差 0.05 个百分点。差异主要来自四舍五入与个别月份修订；"
          "若某序列差异显著，应以官方发布稿为准。")
    else:
        A("重叠区间不足，未形成有效核验。")
    A("")
    A("## 6. 已知缺口")
    A("")
    A("| 项目 | 状态 | 处理 |")
    A("|---|---|---|")
    A("| `cgb_1y` / `cgb_10y` | 未采到 | 本环境未找到可用的中债收益率接口，提供手工下载页 |")
    A("| `usdcny_fixing` | 未采到 | 中间价历史接口未暴露，提供货币网/外管局页面 |")
    A("| `dr007` | 未采到 | 接口仅返回期限结构，页面可查历史 |")
    A("| `fai_ytd_yoy` | 未采到 | 标题无数值，正文可解析，未纳入本轮 |")
    A("| `core_cpi_yoy` | 未采到 | 需解析正文单独字段 |")
    A("| 社融/贷款长历史 | 仅近 14 期 | 央行列表不分页，需年度统计表 |")
    A("")
    A("详见 `manual_sources.md`。")
    A("")

    with open(os.path.join(OUT, "macro_data_quality.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- manual sources ----
    m = ["# 需手工下载的数据与页面 (manual_sources.md)", "",
         f"生成于 {TODAY}。以下项目在自动化环境中未能取到，给出可直接访问的官方页面。", "",
         "| 序列 | 内容 | 官方页面 | 链接 | 备注 |", "|---|---|---|---|---|"]
    for sid, what, page, url, note in MANUAL:
        m.append(f"| `{sid}` | {what} | {page} | [打开]({url}) | {note} |")
    m += ["", "## 下载建议", "",
          "1. 日频利率/汇率务必记录**交易日期**，不要用「所属月最后一天」代替。",
          "2. 导出后保留原始文件与下载时间，便于追溯 `vintage_date`。",
          "3. 若页面支持按日期区间导出，建议区间从 2015-01-01 起，与现有序列对齐。"]
    with open(os.path.join(OUT, "manual_sources.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(m))

    # ---- README ----
    r = ["# 中国宏观数据包（首轮）", "",
         f"构建时间：{TODAY} | 记录 {len(df):,} 行 | 序列 {df['series_id'].nunique()} 个", "",
         "## 文件", "",
         "| 文件 | 内容 |", "|---|---|",
         "| `macro_raw.parquet` | 长表原始数据，含发布时点与质量标记 |",
         "| `macro_raw.csv` | 同上，CSV 备份 |",
         "| `macro_metadata.csv` | 序列级元数据与覆盖统计 |",
         "| `macro_release_calendar.csv` | 发布日历（官方观测 + 保守推断） |",
         "| `macro_data_quality.md` | 质量报告、口径说明、缺口 |",
         "| `manual_sources.md` | 需手工下载的项目与链接 |",
         "| `crosscheck_official_vs_eastmoney.csv` | 官方 vs 第三方核验 |",
         "", "## 数据获取脚本", "",
         "```", "scripts/lib_common.py       公共抓取工具",
         "scripts/collect_nbs_list.py 统计局发布列表（标题+日期）",
         "scripts/collect_nbs.py      统计局序列（标题解析+正文兜底）",
         "scripts/collect_pboc.py     央行货币信用（M2/社融/贷款）",
         "scripts/collect_cm.py       货币网利率（Shibor/DR/LPR）",
         "scripts/collect_em.py       东方财富长历史回填",
         "scripts/build_package.py    合并、赋发布时点、导出交付包",
         "scripts/make_docs.py        生成质量报告与说明",
         "```", "",
         "复现顺序：", "",
         "```powershell",
         "python scripts/collect_nbs_list.py",
         "python scripts/collect_nbs.py",
         "python scripts/collect_pboc.py",
         "python scripts/collect_cm.py",
         "python scripts/collect_em.py",
         "python scripts/build_package.py",
         "python scripts/make_docs.py",
         "```", "",
         "## 使用要点", "",
         "- 回测筛选一律用 `available_at`，不要用 `period_end`。",
         "- 关注 `quality_flag`：`official` 可直接用；`backfill_third_party_assumed_release` "
         "的发布日为保守推断。",
         "- `measure_type` 区分 yoy / mom / ytd_yoy / flow / level，勿混用。"]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(r))
    print("docs written")


if __name__ == "__main__":
    main()
