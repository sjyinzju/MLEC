"""Collect NBS monthly/quarterly series from press releases on www.stats.gov.cn.

Strategy
--------
* Headline series (CPI yoy, PPI yoy/mom, IVA yoy, retail ytd yoy) are parsed
  from the <a title="..."> of list pages: the title carries both the number and
  the release date, so value + release_date come from one authoritative page.
* PMI (headline + new orders + non-manufacturing) and GDP need the article body
  because their titles carry no numbers.
* Everything keeps the official article URL for traceability.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import (CACHE, RAW, ensure_dir, fetch_text,  # noqa: E402
                        strip_tags, write_csv)

LIST_CSV = os.path.join(RAW, "nbs_list_items.csv")
OUT = os.path.join(RAW, "nbs_series.csv")
ART_CACHE = os.path.join(CACHE, "nbs_articles")

CN_NUM_RE = r"([\d]+(?:\.\d+)?)"


def load_items():
    with open(LIST_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def period_from_title(title: str) -> tuple[str | None, str]:
    """Return (period_end, frequency) from a Chinese NBS title."""
    m = re.search(r"(\d{4})年(\d{1,2})月(?:份)?", title)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        # period_end = last day of that month
        import calendar
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}", "M"
    m = re.search(r"(\d{4})年1—(\d{1,2})月份", title)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        import calendar
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}", "M_YTD"
    m = re.search(r"(\d{4})年(\d{1,2})季度", title)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return f"{y}-Q{q}", "Q"
    m = re.search(r"(\d{4})年(上半年|前三季度|全年)", title)
    if m:
        return f"{m.group(1)}-{m.group(2)}", "Q_YTD"
    return None, ""


def parse_titles(items):
    rows = []
    for it in items:
        t, d, u = it["title"], it["date"], it["url"]

        # ---- CPI yoy ----
        m = re.search(r"居民消费价格(?:同比)?(上涨|下降)" + CN_NUM_RE + "%", t)
        if re.search(r"居民消费价格同比持平", t):
            pe, _ = period_from_title(t)
            rows.append(dict(series_id="cpi_yoy", series_name="居民消费价格指数同比",
                             value=0.0, unit="%", measure_type="yoy",
                             frequency="M", period_end=pe, release_date=d,
                             source_url=u, parse_method="list_title_flat"))
            m = None
        if m:
            v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
            pe, fq = period_from_title(t)
            rows.append(dict(series_id="cpi_yoy", series_name="居民消费价格指数同比",
                             value=v, unit="%", measure_type="yoy",
                             frequency="M", period_end=pe, release_date=d,
                             source_url=u, parse_method="list_title"))

        # ---- PPI yoy + mom ----
        m = re.search(r"工业生产者出厂价格同比(上涨|下降)" + CN_NUM_RE + "%", t)
        if m:
            v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
            pe, fq = period_from_title(t)
            rows.append(dict(series_id="ppi_yoy", series_name="工业生产者出厂价格指数同比",
                             value=v, unit="%", measure_type="yoy",
                             frequency="M", period_end=pe, release_date=d,
                             source_url=u, parse_method="list_title"))
            m2 = re.search(r"环比(上涨|下降)" + CN_NUM_RE + "%", t)
            if m2:
                v2 = float(m2.group(2)) * (-1 if m2.group(1) == "下降" else 1)
                rows.append(dict(series_id="ppi_mom", series_name="工业生产者出厂价格指数环比",
                                 value=v2, unit="%", measure_type="mom",
                                 frequency="M", period_end=pe, release_date=d,
                                 source_url=u, parse_method="list_title"))

        # ---- CPI mom (when published on the same title page) ----
        m = re.search(r"居民消费价格环比(上涨|下降)" + CN_NUM_RE + "%", t)
        if m:
            v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
            pe, _ = period_from_title(t)
            rows.append(dict(series_id="cpi_mom", series_name="居民消费价格指数环比",
                             value=v, unit="%", measure_type="mom",
                             frequency="M", period_end=pe, release_date=d,
                             source_url=u, parse_method="list_title"))

        # ---- Industrial value added yoy ----
        if re.search(r"规模以上工业增加值", t) and "增长" in t:
            m = re.search(r"规模以上工业增加值(?:同比)?(增长|下降)" + CN_NUM_RE + "%", t)
            if m:
                v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
                pe, _ = period_from_title(t)
                rows.append(dict(series_id="industrial_va_yoy",
                                 series_name="规模以上工业增加值同比",
                                 value=v, unit="%", measure_type="yoy",
                                 frequency="M", period_end=pe, release_date=d,
                                 source_url=u, parse_method="list_title"))

        # ---- Retail sales (cumulative yoy in title) ----
        if "社会消费品零售总额" in t and "增长" in t:
            m = re.search(r"社会消费品零售总额(?:同比)?(增长|下降)" + CN_NUM_RE + "%", t)
            if m:
                v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
                pe, _ = period_from_title(t)
                rows.append(dict(series_id="retail_sales_ytd_yoy",
                                 series_name="社会消费品零售总额累计同比",
                                 value=v, unit="%", measure_type="ytd_yoy",
                                 frequency="M", period_end=pe, release_date=d,
                                 source_url=u, parse_method="list_title"))
    return rows


def get_article(url: str) -> str:
    ensure_dir(ART_CACHE)
    key = re.sub(r"[^0-9a-zA-Z]", "_", url.split("/")[-1])
    p = os.path.join(ART_CACHE, key + ".txt")
    if os.path.exists(p) and os.path.getsize(p) > 200:
        with open(p, encoding="utf-8") as f:
            return f.read()
    html = fetch_text(url, referer="https://www.stats.gov.cn/sj/zxfb/")
    text = strip_tags(html)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(0.4)
    return text


def pct(text: str, patterns: list[str]):
    for p in patterns:
        m = re.search(p, text)
        if m:
            sign = -1 if (m.group(1) == "下降") else 1
            return sign * float(m.group(2))
    return None


def parse_pmi(items):
    rows = []
    cand = [i for i in items if "采购经理指数运行情况" in i["title"]]
    print(f"PMI articles: {len(cand)}")
    for it in cand:
        pe, _ = period_from_title(it["title"])
        try:
            text = get_article(it["url"])
        except Exception as e:  # noqa: BLE001
            print("  FAIL", it["date"], e)
            continue
        # headline index is a level, not a pct change; the article puts spaces
        # around the full-width brackets, e.g. "制造业采购经理指数（ PMI ）为 50.1%"
        m = re.search(r"制造业采购经理指数\s*[（(]\s*PMI\s*[)）]\s*为\s*([\d.]+)", text)
        if not m:
            m = re.search(r"制造业\s*PMI\s*[）)]?\s*为\s*([\d.]+)", text)
        if m:
            rows.append(dict(series_id="pmi_mfg", series_name="制造业采购经理指数",
                             value=float(m.group(1)), unit="index",
                             measure_type="level", frequency="M",
                             period_end=pe, release_date=it["date"],
                             source_url=it["url"], parse_method="article"))
        m = re.search(r"新订单指数为\s*([\d.]+)%", text)
        if m:
            rows.append(dict(series_id="pmi_new_orders", series_name="制造业PMI新订单指数",
                             value=float(m.group(1)), unit="index",
                             measure_type="level", frequency="M",
                             period_end=pe, release_date=it["date"],
                             source_url=it["url"], parse_method="article"))
        m = re.search(r"非制造业商务活动指数为\s*([\d.]+)%", text)
        if m:
            rows.append(dict(series_id="pmi_nonmfg", series_name="非制造业商务活动指数",
                             value=float(m.group(1)), unit="index",
                             measure_type="level", frequency="M",
                             period_end=pe, release_date=it["date"],
                             source_url=it["url"], parse_method="article"))
    return rows


def parse_gdp(items):
    rows = []
    cand = [i for i in items if "国内生产总值" in i["title"] and "初步核算" in i["title"]]
    print(f"GDP articles: {len(cand)}")
    for it in cand:
        pe, _ = period_from_title(it["title"])
        try:
            text = get_article(it["url"])
        except Exception as e:  # noqa: BLE001
            print("  FAIL", it["date"], e)
            continue
        m = re.search(r"同比增长\s*([\d.]+)%", text)
        if m:
            rows.append(dict(series_id="gdp_real_yoy", series_name="国内生产总值同比（不变价）",
                             value=float(m.group(1)), unit="%", measure_type="yoy",
                             frequency="Q", period_end=pe,
                             release_date=it["date"], source_url=it["url"],
                             parse_method="article"))
    return rows


def parse_fallback(items, existing):
    """For CPI/PPI months whose titles carry no number, read the article body."""
    have = {(r["series_id"], r["period_end"]) for r in existing}
    rows = []
    cands = [i for i in items
             if re.search(r"居民消费价格|工业生产者出厂价格", i["title"])]
    for it in cands:
        pe, _ = period_from_title(it["title"])
        if not pe:
            continue
        need_cpi = ("cpi_yoy", pe) not in have and "居民消费价格" in it["title"]
        need_ppi = ("ppi_yoy", pe) not in have and "工业生产者出厂价格" in it["title"]
        if not (need_cpi or need_ppi):
            continue
        try:
            text = get_article(it["url"])
        except Exception as e:  # noqa: BLE001
            print("  fallback FAIL", it["date"], e)
            continue
        flat, v = False, None
        m = re.search(r"居民消费价格(?:总水平)?同比(上涨|下降)\s*([\d.]+)%", text)
        if m:
            v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
        elif re.search(r"居民消费价格(?:总水平)?同比持平", text):
            flat, v = True, 0.0
        if need_cpi and v is not None:
            rows.append(dict(series_id="cpi_yoy", series_name="居民消费价格指数同比",
                             value=v, unit="%", measure_type="yoy", frequency="M",
                             period_end=pe, release_date=it["date"],
                             source_url=it["url"],
                             parse_method="article_flat" if flat else "article"))
        m = re.search(r"工业生产者出厂价格同比(上涨|下降)\s*([\d.]+)%", text)
        if need_ppi and m:
            v = float(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
            rows.append(dict(series_id="ppi_yoy", series_name="工业生产者出厂价格指数同比",
                             value=v, unit="%", measure_type="yoy", frequency="M",
                             period_end=pe, release_date=it["date"],
                             source_url=it["url"], parse_method="article"))
            m2 = re.search(r"环比(上涨|下降)\s*([\d.]+)%", text)
            if m2:
                v2 = float(m2.group(2)) * (-1 if m2.group(1) == "下降" else 1)
                rows.append(dict(series_id="ppi_mom", series_name="工业生产者出厂价格指数环比",
                                 value=v2, unit="%", measure_type="mom", frequency="M",
                                 period_end=pe, release_date=it["date"],
                                 source_url=it["url"], parse_method="article"))
    print(f"fallback article rows: {len(rows)}")
    return rows


def main():
    items = load_items()
    print("items:", len(items))
    rows = parse_titles(items)
    print("title-parsed rows:", len(rows))
    rows += parse_fallback(items, rows)
    rows += parse_pmi(items)
    rows += parse_gdp(items)
    rows.sort(key=lambda r: (r["series_id"], r["period_end"] or ""))
    write_csv(OUT, rows, ["series_id", "series_name", "value", "unit",
                          "measure_type", "frequency", "period_end",
                          "release_date", "source_url", "parse_method"])
    from collections import Counter
    c = Counter(r["series_id"] for r in rows)
    for k, v in sorted(c.items()):
        print(f"  {k:24s} {v}")


if __name__ == "__main__":
    main()
