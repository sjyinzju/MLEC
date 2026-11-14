"""Shared HTTP/IO helpers for the macro data collectors."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
RAW = os.path.join(ROOT, "data_raw")


def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def fetch_text(url: str, referer: str | None = None, timeout: int = 30,
               retries: int = 3, encodings=("utf-8", "gbk", "gb18030")) -> str:
    last = None
    for i in range(retries):
        try:
            headers = {"User-Agent": UA, "Accept": "text/html,application/json,*/*",
                       "Accept-Language": "zh-CN,zh;q=0.9"}
            if referer:
                headers["Referer"] = referer
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in encodings:
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.2 * (i + 1))
    raise last  # type: ignore[misc]


def fetch_json(url: str, referer: str | None = None, timeout: int = 30):
    txt = fetch_text(url, referer=referer, timeout=timeout)
    return json.loads(txt)


def strip_tags(html: str) -> str:
    import re
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    import csv
    ensure_dir(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")
