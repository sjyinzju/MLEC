"""Backfill long monthly/quarterly history from Eastmoney datacenter API.

Eastmoney republishes official NBS / PBOC / Customs series in machine-readable
form. It is used here for (a) history before the official-site archive window
and (b) cross-checking recent official values. It carries no release date, so
release dates for these rows are handled in build_package.py with documented
conservative rules.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import RAW, UA, ensure_dir, write_csv  # noqa: E402

API = "https://datacenter-web.eastmoney.com/api/data/v1/get"

JOBS = [
    ("RPT_ECONOMY_CPI", "cpi", [
        ("cpi_yoy", "居民消费价格指数同比", "NATIONAL_SAME", "%", "yoy"),
        ("cpi_mom", "居民消费价格指数环比", "NATIONAL_SEQUENTIAL", "%", "mom"),
    ]),
    ("RPT_ECONOMY_PPI", "ppi", [
        ("ppi_yoy", "工业生产者出厂价格指数同比", "BASE_SAME", "%", "yoy"),
    ]),
    ("RPT_ECONOMY_PMI", "pmi", [
        ("pmi_mfg", "制造业采购经理指数", "MAKE_INDEX", "index", "level"),
        ("pmi_nonmfg", "非制造业商务活动指数", "NMAKE_INDEX", "index", "level"),
    ]),
    ("RPT_ECONOMY_GDP", "gdp", [
        ("gdp_real_yoy", "国内生产总值同比（不变价）", "SUM_SAME", "%", "yoy"),
    ]),
    ("RPT_ECONOMY_CURRENCY_SUPPLY", "money", [
        ("m2_yoy", "广义货币M2余额同比", "BASIC_CURRENCY_SAME", "%", "yoy"),
        ("m1_yoy", "狭义货币M1余额同比", "CURRENCY_SAME", "%", "yoy"),
    ]),
    ("RPT_ECONOMY_CUSTOMS", "trade", [
        ("exports_yoy", "出口金额同比（美元计）", "EXIT_BASE_SAME", "%", "yoy"),
        ("imports_yoy", "进口金额同比（美元计）", "IMPORT_BASE_SAME", "%", "yoy"),
    ]),
]


def get_page(report: str, page: int, size: int = 500) -> dict:
    q = {"reportName": report, "columns": "ALL", "pageNumber": str(page),
         "pageSize": str(size), "sortColumns": "REPORT_DATE",
         "sortTypes": "1"}
    url = API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://data.eastmoney.com/"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return {}


def main():
    ensure_dir(RAW)
    all_rows = []
    for report, tag, cols in JOBS:
        rows, page = [], 1
        while True:
            j = get_page(report, page)
            res = j.get("result") or {}
            data = res.get("data") or []
            if not data:
                break
            rows.extend(data)
            pages = res.get("pages") or 1
            print(f"  {report} page {page}/{pages} rows={len(rows)}", flush=True)
            if page >= pages:
                break
            page += 1
            time.sleep(0.35)
        for sid, name, key, unit, mtype in cols:
            out = []
            for r in rows:
                v = r.get(key)
                if v is None:
                    continue
                d = (r.get("REPORT_DATE") or "")[:10]
                if not d:
                    continue
                freq = "Q" if report == "RPT_ECONOMY_GDP" else "M"
                out.append({"series_id": sid, "series_name": name,
                            "value": v, "unit": unit, "measure_type": mtype,
                            "frequency": freq, "period_end": d,
                            "release_date": "", "source_url": API,
                            "parse_method": "eastmoney:" + report})
            print(f"    {sid}: {len(out)}")
            all_rows.extend(out)

    all_rows.sort(key=lambda r: (r["series_id"], r["period_end"]))
    path = os.path.join(RAW, "em_series.csv")
    write_csv(path, all_rows, ["series_id", "series_name", "value", "unit",
                               "measure_type", "frequency", "period_end",
                               "release_date", "source_url", "parse_method"])


if __name__ == "__main__":
    main()
