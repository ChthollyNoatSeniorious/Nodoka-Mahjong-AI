#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find the concrete bigcoach API call sites inside the JS bundles.

The app builds URLs dynamically (template literals), so a plain path regex
misses them.  We dump the bundles and print surrounding context for the words
seen in the network log: submit / progress / result / classic / tasks.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
CACHE = pathlib.Path(r"reviewer\out\_bundles")
CACHE.mkdir(parents=True, exist_ok=True)


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cookie": COOKIE, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


html = get(BASE + "/hall-of-fame")
assets = re.findall(r'<script[^>]+src="([^"]+)"', html)
js_files = []
for a in assets:
    if not a.endswith(".js"):
        continue
    url = a if a.startswith("http") else (BASE + a if a.startswith("/") else BASE + "/" + a)
    name = url.split("/")[-1].split("?")[0]
    dest = CACHE / name
    if not dest.is_file():
        dest.write_text(get(url), encoding="utf-8")
    js_files.append(dest)

print(f"cached {len(js_files)} bundles in {CACHE}")
print()

KEYS = ["submit", "progress", "classic", "tasks", "paipu", "review"]
for f in js_files:
    txt = f.read_text(encoding="utf-8", errors="replace")
    hits = []
    for k in KEYS:
        for m in re.finditer(re.escape(k), txt, re.I):
            s = max(0, m.start() - 90)
            e = min(len(txt), m.end() + 90)
            snippet = txt[s:e].replace("\n", " ")
            hits.append((k, snippet))
    if not hits:
        continue
    print(f"===== {f.name} ({len(hits)} hits) =====")
    seen = set()
    for k, sn in hits:
        # keep only snippets that look like a URL construction
        if "/api" in sn or "`" in sn or "${" in sn:
            key = sn[:70]
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{k}] ...{sn}...")
    print()
