"""Collect daily/monthly policy rates from chinamoney (CFETS) official APIs.

Sources
-------
Shibor (1W, 3M), DR007 : https://www.chinamoney.com.cn/ags/ms/cm-u-bk-{shibor,currency}/...
LPR 1Y/5Y              : https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis

Notes
-----
* Shibor was launched 2006-10-08; pre-2007 coverage is therefore absent by
  construction (documented, not filled).
* DR007 is a depository-institution 7-day repo rate published from 2014-12.
* LPR: the current quoting mechanism starts 2019-08-20 (monthly); the earlier
  2013-10..2019-08 series is a different regime and is NOT mixed in here.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import RAW, ensure_dir, fetch_json, write_csv  # noqa: E402

REF = "https://www.chinamoney.com.cn/chinese/"
BASE = "https://www.chinamoney.com.cn/ags/ms/"


def shibor_chunk(start: str, end: str) -> list[dict]:
    url = (BASE + "cm-u-bk-shibor/ShiborHis?lang=CN"
           f"&startDate={start}&endDate={end}")
    j = fetch_json(url, referer=REF)
    out = []
    for r in j.get("records") or []:
        d = r.get("showDateCN") or r.get("showDateEN")
        if not d:
            continue
        out.append({
            "trade_date": d,
            "shibor_1w": r.get("1W"),
            "shibor_3m": r.get("3M"),
            "shibor_on": r.get("ON") or r.get("O/N"),
        })
    return out


def dr_chunk(start: str, end: str) -> list[dict]:
    url = (BASE + "cm-u-bk-currency/DrHis?lang=CN"
           f"&startDate={start}&endDate={end}")
    j = fetch_json(url, referer=REF)
    recs = j.get("records") or []
    out = []
    for r in recs:
        d = r.get("showDateCN") or r.get("showDateEN")
        if not d:
            continue
        # key names vary; take DR007-like fields
        val = r.get("DR007") or r.get("dr007")
        if val is None:
            for k, v in r.items():
                if k.upper().startswith("DR"):
                    val = v
                    break
        out.append({"trade_date": d, "dr007": val})
    return out


def lpr_chunk(start: str, end: str) -> list[dict]:
    url = (BASE + "cm-u-bk-currency/LprHis?lang=CN"
           f"&startDate={start}&endDate={end}")
    j = fetch_json(url, referer=REF)
    out = []
    for r in j.get("records") or []:
        d = r.get("showDateCN")
        if not d:
            continue
        out.append({"trade_date": d, "lpr_1y": r.get("1Y"),
                    "lpr_5y": r.get("5Y")})
    return out


def year_ranges(y0: int, y1: int):
    today = dt.date.today().isoformat()
    for y in range(y0, y1 + 1):
        s = f"{y}-01-01"
        e = f"{y}-12-31" if y < dt.date.today().year else today
        yield s, e


def main():
    ensure_dir(RAW)

    # ---- Shibor 1W / 3M from 2006 (launch year) ----
    rows, seen = [], set()
    for s, e in year_ranges(2006, dt.date.today().year):
        try:
            part = shibor_chunk(s, e)
        except Exception as ex:  # noqa: BLE001
            print(f"shibor {s}..{e} FAIL {ex}")
            continue
        for r in part:
            if r["trade_date"] not in seen:
                seen.add(r["trade_date"])
                rows.append(r)
        print(f"shibor {s}..{e}: +{len(part)} total={len(rows)}", flush=True)
        time.sleep(0.3)
    rows.sort(key=lambda r: r["trade_date"])
    write_csv(os.path.join(RAW, "cm_shibor_daily.csv"), rows,
              ["trade_date", "shibor_on", "shibor_1w", "shibor_3m"])

    # ---- DR007 ----
    rows, seen = [], set()
    for s, e in year_ranges(2014, dt.date.today().year):
        try:
            part = dr_chunk(s, e)
        except Exception as ex:  # noqa: BLE001
            print(f"dr007 {s}..{e} FAIL {ex}")
            continue
        for r in part:
            if r["trade_date"] not in seen and r["dr007"]:
                seen.add(r["trade_date"])
                rows.append(r)
        print(f"dr007 {s}..{e}: +{len(part)} total={len(rows)}", flush=True)
        time.sleep(0.3)
    rows.sort(key=lambda r: r["trade_date"])
    write_csv(os.path.join(RAW, "cm_dr007_daily.csv"), rows,
              ["trade_date", "dr007"])

    # ---- LPR (post-2019 regime) ----
    rows, seen = [], set()
    for s, e in year_ranges(2019, dt.date.today().year):
        try:
            part = lpr_chunk(s, e)
        except Exception as ex:  # noqa: BLE001
            print(f"lpr {s}..{e} FAIL {ex}")
            continue
        for r in part:
            if r["trade_date"] not in seen:
                seen.add(r["trade_date"])
                rows.append(r)
        print(f"lpr {s}..{e}: +{len(part)} total={len(rows)}", flush=True)
        time.sleep(0.3)
    rows.sort(key=lambda r: r["trade_date"])
    write_csv(os.path.join(RAW, "cm_lpr_monthly.csv"), rows,
              ["trade_date", "lpr_1y", "lpr_5y"])


if __name__ == "__main__":
    main()
