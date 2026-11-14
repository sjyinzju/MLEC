"""Collect PBOC 金融统计数据报告: M2 yoy, TSF stock yoy, new RMB loans.

The PBOC list page for 金融统计数据报告 exposes only ~14 recent reports and
does not paginate (index_1.html -> 404), so this collector yields the recent
official window. Longer history is backfilled from Eastmoney and flagged in
macro_data_quality.md.
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import CACHE, RAW, ensure_dir, fetch_text, strip_tags, write_csv  # noqa: E402

LIST = "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html"
OUT = os.path.join(RAW, "pboc_series.csv")
ART = os.path.join(CACHE, "pboc_articles")


def period_of(title: str):
    m = re.search(r"(\d{4})年(\d{1,2})月", title)
    if m:
        import calendar
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}", "M"
    m = re.search(r"(\d{4})年(前三季度|上半年|一季度|全年)", title)
    if m:
        return f"{m.group(1)}-{m.group(2)}", "YTD"
    return None, ""


def main():
    html = fetch_text(LIST, referer="https://www.pbc.gov.cn/")
    reports = []
    seen = set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        t = strip_tags(inner)
        if "金融统计数据报告" in t and href not in seen:
            seen.add(href)
            url = href if href.startswith("http") else "https://www.pbc.gov.cn" + href
            reports.append((t, url))
    print("reports found:", len(reports))

    ensure_dir(ART)
    rows = []
    for title, url in reports:
        pe, fq = period_of(title)
        key = re.sub(r"[^0-9a-zA-Z]", "_", url.split("/")[-2])
        p = os.path.join(ART, key + ".txt")
        if os.path.exists(p) and os.path.getsize(p) > 200:
            text = open(p, encoding="utf-8").read()
        else:
            try:
                text = strip_tags(fetch_text(url, referer=LIST))
            except Exception as e:  # noqa: BLE001
                print("  FAIL", title, e)
                continue
            open(p, "w", encoding="utf-8").write(text)
            time.sleep(0.5)

        # release date is embedded in the article id: /2026101417073743604/
        rel = ""
        mid = url.rstrip("/").split("/")[-2] if url.rstrip("/").endswith("index.html") else ""
        mrel = re.match(r"(20\d{2})(\d{2})(\d{2})", mid or "")

        m = re.search(r"广义货币\s*[（(]?\s*M2\s*[)）]?\s*余额[^。]{0,60}?同比增长\s*([\d.]+)%", text)
        if m:
            rows.append(dict(series_id="m2_yoy", series_name="广义货币M2余额同比",
                             value=float(m.group(1)), unit="%", measure_type="yoy",
                             frequency=fq, period_end=pe, release_date=(
                                 f"{mrel.group(1)}-{mrel.group(2)}-{mrel.group(3)}"
                                 if mrel else ""),
                             source_url=url, parse_method="article"))
        m = re.search(r"社会融资规模存量[^。]{0,60}?同比增长\s*([\d.]+)%", text)
        if m:
            rows.append(dict(series_id="tsf_stock_yoy", series_name="社会融资规模存量同比",
                             value=float(m.group(1)), unit="%", measure_type="yoy",
                             frequency=fq, period_end=pe, release_date=(
                                 f"{mrel.group(1)}-{mrel.group(2)}-{mrel.group(3)}"
                                 if mrel else ""),
                             source_url=url, parse_method="article"))
        m = re.search(r"人民币贷款增加\s*([\d.]+)\s*万亿元", text)
        unit, val = "万亿元", None
        if m:
            val = float(m.group(1))
            rows.append(dict(series_id="new_rmb_loans", series_name="当月新增人民币贷款",
                             value=val * 10000, unit="亿元", measure_type="flow",
                             frequency=fq, period_end=pe, release_date=(
                                 f"{mrel.group(1)}-{mrel.group(2)}-{mrel.group(3)}"
                                 if mrel else ""),
                             source_url=url, parse_method="article"))
        print(f"  {title}: {'ok' if rows else 'none'}")

    rows.sort(key=lambda r: (r["series_id"], r["period_end"] or ""))
    write_csv(OUT, rows, ["series_id", "series_name", "value", "unit",
                          "measure_type", "frequency", "period_end",
                          "release_date", "source_url", "parse_method"])
    from collections import Counter
    for k, v in sorted(Counter(r["series_id"] for r in rows).items()):
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
