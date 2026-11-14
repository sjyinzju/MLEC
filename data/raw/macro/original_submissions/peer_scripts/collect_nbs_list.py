"""Collect NBS monthly press-release list items (title + release date + url).

The NBS list pages publish headline numbers inside the <a title="..."> attribute,
and the release date in the same <li>. That gives value + release_date in one go,
without parsing article bodies.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BASE = "https://www.stats.gov.cn/sj/zxfb/"
CACHE = os.path.join("cache", "nbs")
OUT = os.path.join("data_raw", "nbs_list_items.csv")
CUTOFF = "2015-01-01"
MAX_PAGES = 260


def fetch(url, timeout=30, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "text/html,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.stats.gov.cn/sj/zxfb/",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last  # type: ignore[misc]


def cache_path(page: int) -> str:
    name = "index.html" if page == 0 else f"index_{page}.html"
    return os.path.join(CACHE, name)


def get_page(page: int) -> str:
    p = cache_path(page)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    url = BASE + ("index.html" if page == 0 else f"index_{page}.html")
    html = fetch(url)
    os.makedirs(CACHE, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    return html


def parse_items(html: str):
    out = []
    for li in re.findall(r"<li>(.*?)</li>", html, re.S):
        m = re.search(r'href="([^"]+t\d{8}_\d+\.html)"', li)
        t = re.search(r"title='([^']+)'", li)
        d = re.search(r"(20\d{2}-\d{2}-\d{2})", li)
        if m and t and d:
            href = m.group(1)
            if href.startswith("./"):
                href = BASE + href[2:]
            elif href.startswith("/"):
                href = "https://www.stats.gov.cn" + href
            out.append({"title": t.group(1).strip(), "date": d.group(1),
                        "url": href})
    # dedupe by url
    seen, uniq = set(), []
    for r in out:
        if r["url"] not in seen:
            seen.add(r["url"])
            uniq.append(r)
    return uniq


def main():
    rows, oldest = [], None
    for page in range(MAX_PAGES):
        try:
            html = get_page(page)
        except Exception as e:  # noqa: BLE001
            print(f"page {page} FAIL {e}", flush=True)
            break
        items = parse_items(html)
        if not items:
            print(f"page {page}: no items, stop", flush=True)
            break
        rows.extend(items)
        oldest = min(r["date"] for r in items)
        print(f"page {page:3d} items={len(items):3d} oldest={oldest} total={len(rows)}",
              flush=True)
        if oldest < CUTOFF:
            print("reached cutoff", CUTOFF, flush=True)
            break
        time.sleep(0.35)

    seen, uniq = set(), []
    for r in rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            uniq.append(r)
    uniq.sort(key=lambda r: r["date"], reverse=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date", "title", "url"])
        w.writeheader()
        w.writerows(uniq)
    print(f"\nwrote {len(uniq)} items -> {OUT}")
    print("oldest:", uniq[-1]["date"] if uniq else None)

    # quick topic census
    pats = {
        "CPI": r"居民消费价格",
        "PPI": r"工业生产者出厂价格",
        "PMI": r"采购经理指数",
        "IVA": r"规模以上工业增加值",
        "RETAIL": r"社会消费品零售总额",
        "FAI": r"固定资产投资",
        "GDP": r"国内生产总值",
    }
    for k, p in pats.items():
        n = sum(1 for r in uniq if re.search(p, r["title"]))
        print(f"  {k:7s} {n}")


if __name__ == "__main__":
    main()
