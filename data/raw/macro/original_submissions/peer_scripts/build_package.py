"""Build the delivery package: parquet, metadata, release calendar, quality report.

Merge order (highest priority first):
  1. Official exact-date sources scraped here (NBS list pages / articles, PBOC
     reports, CFETS-chinamoney APIs).
  2. Eastmoney datacenter backfill for periods the official archive window does
     not cover. These rows carry no release date of their own, so release dates
     are assigned by a documented conservative rule and flagged quality_flag.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import RAW, ROOT, ensure_dir  # noqa: E402

OUTDIR = os.path.join(ROOT, "deliverables")
NOW = dt.datetime(2026, 11, 12, 11, 55, tzinfo=dt.timezone(dt.timedelta(hours=8)))
NOW_S = NOW.isoformat(timespec="seconds")

SOURCE_META = {
    "nbs": ("国家统计局", "https://www.stats.gov.cn/sj/zxfb/"),
    "pboc": ("中国人民银行", "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html"),
    "cm": ("中国外汇交易中心/全国银行间同业拆借中心", "https://www.chinamoney.com.cn/"),
    "em": ("东方财富宏观数据中心（转载官方数据）", "https://datacenter-web.eastmoney.com/api/data/v1/get"),
}

SERIES_META = {
    "pmi_mfg": ("制造业采购经理指数", "指数", "level", "月", "国家统计局/中国物流与采购联合会"),
    "pmi_new_orders": ("制造业PMI新订单指数", "指数", "level", "月", "国家统计局/中国物流与采购联合会"),
    "pmi_nonmfg": ("非制造业商务活动指数", "指数", "level", "月", "国家统计局/中国物流与采购联合会"),
    "industrial_va_yoy": ("规模以上工业增加值同比", "%", "yoy", "月", "国家统计局"),
    "retail_sales_ytd_yoy": ("社会消费品零售总额累计同比", "%", "ytd_yoy", "月", "国家统计局"),
    "cpi_yoy": ("居民消费价格指数同比", "%", "yoy", "月", "国家统计局"),
    "cpi_mom": ("居民消费价格指数环比", "%", "mom", "月", "国家统计局"),
    "ppi_yoy": ("工业生产者出厂价格指数同比", "%", "yoy", "月", "国家统计局"),
    "ppi_mom": ("工业生产者出厂价格指数环比", "%", "mom", "月", "国家统计局"),
    "m2_yoy": ("广义货币M2余额同比", "%", "yoy", "月", "中国人民银行"),
    "m1_yoy": ("狭义货币M1余额同比", "%", "yoy", "月", "中国人民银行"),
    "tsf_stock_yoy": ("社会融资规模存量同比", "%", "yoy", "月", "中国人民银行"),
    "new_rmb_loans": ("当月新增人民币贷款", "亿元", "flow", "月", "中国人民银行"),
    "gdp_real_yoy": ("国内生产总值同比（不变价）", "%", "yoy", "季", "国家统计局"),
    "exports_yoy": ("出口金额同比（美元计）", "%", "yoy", "月", "海关总署"),
    "imports_yoy": ("进口金额同比（美元计）", "%", "yoy", "月", "海关总署"),
    "shibor_1w": ("Shibor 1周", "%", "level", "日", "全国银行间同业拆借中心"),
    "shibor_3m": ("Shibor 3个月", "%", "level", "日", "全国银行间同业拆借中心"),
    "lpr_1y": ("1年期贷款市场报价利率LPR", "%", "level", "日(月度发布)", "中国人民银行授权全国银行间同业拆借中心"),
}

# Conservative assumed release rules for third-party backfilled rows.
# (month offset after period end, day of that month, time of day, note)
ASSUMED_RULES = {
    "cpi_yoy": (1, 15, "09:30", "统计局月度CPI/PPI通常在次月9—15日发布，此处按下一次月15日保守假定"),
    "cpi_mom": (1, 15, "09:30", "同上，保守假定次月15日"),
    "ppi_yoy": (1, 15, "09:30", "同上，保守假定次月15日"),
    "ppi_mom": (1, 15, "09:30", "同上，保守假定次月15日"),
    "industrial_va_yoy": (1, 20, "10:00", "规上工业增加值通常随月度国民经济运行情况于次月15—20日发布，保守假定20日"),
    "retail_sales_ytd_yoy": (1, 20, "10:00", "社零总额随月度经济运行情况发布，保守假定次月20日"),
    "pmi_mfg": (0, 0, "09:30", "PMI于当月最后一日09:30发布，取当月最后一日"),
    "pmi_nonmfg": (0, 0, "09:30", "同上，取当月最后一日"),
    "m2_yoy": (1, 15, "16:00", "央行金融统计数据通常在次月10—15日16:00前后发布，保守假定15日"),
    "m1_yoy": (1, 15, "16:00", "同上"),
    "tsf_stock_yoy": (1, 15, "16:00", "同上"),
    "new_rmb_loans": (1, 15, "16:00", "同上"),
    "gdp_real_yoy": (1, 20, "10:00", "季度GDP初步核算通常在季后次月17—20日发布，保守假定20日"),
    "exports_yoy": (1, 13, "11:00", "海关总署进出口数据通常次月7—13日发布，保守假定13日"),
    "imports_yoy": (1, 13, "11:00", "同上"),
}


def norm_period(pe: str, freq: str) -> str:
    """Normalise period_end to month-end / quarter-end ISO date.

    NBS list pages give month-end dates, Eastmoney gives the first day of the
    month, PBOC mixes YTD labels. Without this the same economic period would
    appear twice under different dates.
    """
    s = str(pe).strip()
    if not s:
        return s
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s[:10])
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if freq and (freq.startswith("Q") or freq == "季"):
            q_end_month = ((mo - 1) // 3 + 1) * 3
            return dt.date(y, q_end_month,
                           calendar.monthrange(y, q_end_month)[1]).isoformat()
        return dt.date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
    m = re.fullmatch(r"(\d{4})-Q([1-4])", s)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        mo = q * 3
        return dt.date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
    m = re.fullmatch(r"(\d{4})-(上半年|前三季度|一季度|全年)", s)
    if m:
        y = int(m.group(1))
        mo = {"一季度": 3, "上半年": 6, "前三季度": 9, "全年": 12}[m.group(2)]
        return dt.date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
    return s


def load_raw() -> pd.DataFrame:
    frames = []
    for fn, src in [("nbs_series.csv", "nbs"), ("pboc_series.csv", "pboc"),
                    ("em_series.csv", "em")]:
        p = os.path.join(RAW, fn)
        if not os.path.exists(p):
            print("missing", p)
            continue
        df = pd.read_csv(p, encoding="utf-8-sig", dtype=str)
        df["src_tag"] = src
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_rates() -> pd.DataFrame:
    rows = []
    sh = os.path.join(RAW, "cm_shibor_daily.csv")
    if os.path.exists(sh):
        d = pd.read_csv(sh, encoding="utf-8-sig", dtype=str)
        for col, sid in [("shibor_1w", "shibor_1w"), ("shibor_3m", "shibor_3m")]:
            if col in d.columns:
                for _, r in d.iterrows():
                    if pd.notna(r[col]) and str(r[col]).strip():
                        rows.append({"series_id": sid, "value": float(r[col]),
                                     "trade_date": r["trade_date"]})
    lp = os.path.join(RAW, "cm_lpr_monthly.csv")
    if os.path.exists(lp):
        d = pd.read_csv(lp, encoding="utf-8-sig", dtype=str)
        for _, r in d.iterrows():
            if pd.notna(r.get("lpr_1y")) and str(r["lpr_1y"]).strip():
                rows.append({"series_id": "lpr_1y", "value": float(r["lpr_1y"]),
                             "trade_date": r["trade_date"]})
    return pd.DataFrame(rows)


def add_months(d: dt.date, months: int) -> dt.date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, day)


def clean(x) -> str:
    """Normalise pandas/CSV artefacts: None, NaN, 'nan', 'None' -> ''."""
    if x is None:
        return ""
    s = str(x).strip()
    return "" if s.lower() in ("nan", "none", "") else s


def assumed_release(sid: str, period_end: str) -> tuple[str, str, str]:
    """Return (release_date, release_time, note) for a backfilled row."""
    rule = ASSUMED_RULES.get(sid)
    try:
        pe = dt.date.fromisoformat(period_end[:10])
    except ValueError:
        return "", "", "非标准期末日期，未赋发布日"
    if not rule:
        return "", "", "无发布规则"
    off, day, tod, note = rule
    base = add_months(pe.replace(day=1), off)
    if day == 0:  # last day of the period month itself (PMI)
        day = calendar.monthrange(base.year, base.month)[1]
    day = min(day, calendar.monthrange(base.year, base.month)[1])
    return base.replace(day=day).isoformat(), tod, note


def main():
    ensure_dir(OUTDIR)
    raw = load_raw()
    rates = load_rates()

    rows = []
    # ---------- macro series ----------
    for sid, g in raw.groupby("series_id"):
        if sid not in SERIES_META:
            continue
        name, unit, mtype, freq_cn, official_owner = SERIES_META[sid]
        # priority: nbs > pboc > em
        order = {"nbs": 0, "pboc": 1, "em": 2}
        g = g.assign(_pri=g["src_tag"].map(order)).sort_values("_pri")
        seen = set()
        for _, r in g.iterrows():
            freq_v = str(r.get("frequency") or SERIES_META[sid][3])
            pe = norm_period(str(r["period_end"]), freq_v)
            if pe in seen:
                continue
            seen.add(pe)
            src_tag = r["src_tag"]
            src_name, src_url = SOURCE_META[src_tag]
            rd = clean(r.get("release_date"))
            rt, note, quality = "", "", ""
            if src_tag == "em" or not rd:
                rd2, rt2, note2 = assumed_release(sid, pe)
                rd = rd or rd2
                rt = rt2
                note = note2
                quality = ("backfill_third_party_assumed_release" if src_tag == "em"
                           else "official_value_assumed_release")
                # a value we already hold cannot have a future release date;
                # cap the conservative assumption at the retrieval date
                if rd and rd > NOW.date().isoformat():
                    rd = NOW.date().isoformat()
                    note = (note or "") + "；假定发布日晚于获取日，已按获取日封顶"
            else:
                rt = "09:30" if src_tag == "nbs" else "16:00"
                note = "官方发布页面标注日期"
                quality = "official"
            avail = f"{rd}T{rt or '18:00'}:00+08:00" if rd else ""
            val = r["value"]
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            rows.append({
                "series_id": sid,
                "series_name": name,
                "observation_period": pe[:7] if len(pe) >= 7 else pe,
                "period_end": pe,
                "value": val,
                "unit": r.get("unit") or unit,
                "measure_type": r.get("measure_type") or mtype,
                "frequency": r.get("frequency") or freq_cn,
                "release_date": rd,
                "release_time": rt,
                "available_at": avail,
                "source_name": src_name,
                "source_url": (r.get("source_url") if isinstance(r.get("source_url"), str)
                               and str(r.get("source_url")).startswith("http") else src_url),
                "retrieved_at": NOW_S,
                "vintage_date": "2026-11-12",
                "revision_flag": "latest_vintage" if src_tag != "nbs" else "as_published",
                "adjustment_note": note,
                "quality_flag": quality,
                "parse_method": r.get("parse_method") or "",
            })

    # ---------- daily/monthly rates ----------
    for _, r in rates.iterrows():
        sid = r["series_id"]
        name, unit, mtype, freq_cn, owner = SERIES_META[sid]
        td = str(r["trade_date"])[:10]
        try:
            dt.date.fromisoformat(td)
        except ValueError:
            continue
        tod = "11:00" if sid.startswith("shibor") else "09:15"
        rows.append({
            "series_id": sid, "series_name": name,
            "observation_period": td[:7], "period_end": td,
            "value": float(r["value"]), "unit": unit, "measure_type": mtype,
            "frequency": freq_cn,
            "release_date": td, "release_time": tod,
            "available_at": f"{td}T{tod}:00+08:00",
            "source_name": SOURCE_META["cm"][0],
            "source_url": "https://www.chinamoney.com.cn/chinese/bkshibor/"
                          if sid.startswith("shibor")
                          else "https://www.chinamoney.com.cn/chinese/bklpr/",
            "retrieved_at": NOW_S, "vintage_date": "2026-11-12",
            "revision_flag": "latest_vintage",
            "adjustment_note": ("Shibor 2006-10-08 起发布；无当日报价的日期不填补"
                                if sid.startswith("shibor")
                                else "LPR 接口仅返回最近12期，历史需另行下载"),
            "quality_flag": "official",
            "parse_method": "chinamoney_api",
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no rows built")

    df = df[df["period_end"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")].copy()
    print(f"dropped rows with unusable period_end: {len(rows) - len(df)}")
    df = df.drop_duplicates(subset=["series_id", "period_end"]).copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df.sort_values(["series_id", "period_end"]).reset_index(drop=True)
    df["row_id"] = [hashlib.md5(f"{a}|{b}".encode()).hexdigest()[:12]
                    for a, b in zip(df["series_id"], df["period_end"])]

    cols = ["row_id", "series_id", "series_name", "observation_period",
            "period_end", "value", "unit", "measure_type", "frequency",
            "release_date", "release_time", "available_at", "source_name",
            "source_url", "retrieved_at", "vintage_date", "revision_flag",
            "adjustment_note", "quality_flag", "parse_method"]
    df = df[cols]

    pq = os.path.join(OUTDIR, "macro_raw.parquet")
    df.to_parquet(pq, index=False)
    print(f"parquet -> {pq}  rows={len(df)} cols={len(df.columns)}")

    df.to_csv(os.path.join(OUTDIR, "macro_raw.csv"), index=False,
              encoding="utf-8-sig")

    # ---------- metadata ----------
    meta = []
    for sid, g in df.groupby("series_id"):
        name, unit, mtype, freq_cn, owner = SERIES_META.get(
            sid, (sid, "", "", "", ""))
        meta.append({
            "series_id": sid, "series_name": name, "unit": unit,
            "measure_type": mtype, "frequency": freq_cn,
            "owner_institution": owner,
            "obs_count": len(g),
            "first_period": g["period_end"].min(),
            "last_period": g["period_end"].max(),
            "first_release_date": g["release_date"].replace("", np.nan).min(),
            "last_release_date": g["release_date"].replace("", np.nan).max(),
            "n_official_rows": int((g["quality_flag"] == "official").sum()),
            "n_backfill_rows": int(g["quality_flag"].str.startswith("backfill").sum()),
            "n_assumed_release_rows": int((g["quality_flag"] == "official_value_assumed_release").sum()),
            "primary_source_url": g["source_url"].iloc[0],
            "priority": "P0" if sid in P0 else ("P1" if sid in P1 else "P2"),
            "coverage_note": "",
        })
    mdf = pd.DataFrame(meta).sort_values(["priority", "series_id"])
    mdf.to_csv(os.path.join(OUTDIR, "macro_metadata.csv"), index=False,
               encoding="utf-8-sig")
    print("metadata rows", len(mdf))

    # ---------- release calendar ----------
    cal = df[df["release_date"].astype(str).str.len() >= 10][
        ["release_date", "release_time", "series_id", "series_name",
         "period_end", "source_name", "quality_flag", "available_at"]
    ].copy()
    cal["calendar_type"] = np.where(cal["quality_flag"] == "official",
                                    "observed_official", "inferred_conservative")
    cal = cal.sort_values(["release_date", "series_id"])
    cal.to_csv(os.path.join(OUTDIR, "macro_release_calendar.csv"), index=False,
               encoding="utf-8-sig")
    print("calendar rows", len(cal))

    # ---------- cross-check official vs eastmoney (before de-dup) ----------
    checks = []
    em_raw = raw[raw["src_tag"] == "em"]
    off_raw = raw[raw["src_tag"] != "em"]
    for sid in ["cpi_yoy", "ppi_yoy", "pmi_mfg", "m2_yoy", "exports_yoy",
                "gdp_real_yoy"]:
        o = off_raw[off_raw["series_id"] == sid][["period_end", "value"]].copy()
        e = em_raw[em_raw["series_id"] == sid][["period_end", "value"]].copy()
        o["period_end"] = [norm_period(x, "M") for x in o["period_end"]]
        e["period_end"] = [norm_period(x, "M") for x in e["period_end"]]
        if o.empty or e.empty:
            continue
        o = o.assign(value=pd.to_numeric(o["value"], errors="coerce"))
        e = e.assign(value=pd.to_numeric(e["value"], errors="coerce"))
        j = o.merge(e, on="period_end", suffixes=("_off", "_em")).dropna()
        if len(j) == 0:
            continue
        diff = (j["value_off"] - j["value_em"]).abs()
        checks.append({
            "series_id": sid, "overlap_n": len(j),
            "max_abs_diff": round(float(diff.max()), 4),
            "mean_abs_diff": round(float(diff.mean()), 4),
            "mismatch_gt_tol": int((diff > 0.05).sum()),
        })
    ck = pd.DataFrame(checks)
    ck.to_csv(os.path.join(OUTDIR, "crosscheck_official_vs_eastmoney.csv"),
              index=False, encoding="utf-8-sig")
    print(ck.to_string(index=False))

    json.dump({"built_at": NOW_S, "rows": int(len(df)),
               "series": int(df["series_id"].nunique())},
              open(os.path.join(OUTDIR, "build_info.json"), "w"),
              ensure_ascii=False, indent=2)


P0 = {"pmi_mfg", "pmi_new_orders", "industrial_va_yoy", "retail_sales_ytd_yoy",
      "cpi_yoy", "ppi_yoy", "m2_yoy", "tsf_stock_yoy", "new_rmb_loans",
      "shibor_1w", "shibor_3m", "cgb_1y", "cgb_10y", "usdcny_fixing",
      "exports_yoy"}
P1 = {"gdp_real_yoy", "fai_ytd_yoy", "pmi_nonmfg", "cpi_mom", "core_cpi_yoy",
      "m1_yoy", "tsf_flow", "loan_balance_yoy", "dr007", "lpr_1y",
      "imports_yoy", "fx_reserves"}


if __name__ == "__main__":
    main()
