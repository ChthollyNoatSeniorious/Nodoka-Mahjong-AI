#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download full event games listing and dump structure summary."""
import json
import sys
import re
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
API = "https://review.bigcoach.work/api/v2"

# paginate: total=382, page size 50 -> 8 pages
items_all = []
for page in range(1, 20):
    url = f"{API}/events/69289369/games?page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8", "replace")
    obj = json.loads(body)
    data = obj["data"]
    items = data.get("items", [])
    items_all += items
    print(f"page {page}: {len(items)} items (total so far {len(items_all)})",
          flush=True)
    if len(items) < 50:
        break

dedup = {it["uuid"]: it for it in items_all}
print("collected:", len(items_all), "unique:", len(dedupped :=
      list(dedup.values())) or 0, flush=True)
print("item keys:", list(items_all[0].keys()), flush=True)
it = items_all[0]
for k, v in it.items():
    s = json.dumps(v, ensure_ascii=False)
    print(f"  {k}: {s[:400]}", flush=True)
seats = it.get("seats") or []
print("num seats:", len(seats), flush=True)
if seats:
    for i, s in enumerate(seats):
        print(f"  seat[{i}]: {json.dumps(s, ensure_ascii=False)[:300]}",
              flush=True)
# collect all task ids
allids = set()
for g in items_all:
    for s in g.get("seats") or []:
        if s.get("taskId"):
            allids.add(s["taskId"])
print("distinct taskIds:", len(allids), flush=True)
open("reviewer/out/_event_69289369.json", "w", encoding="utf-8").write(
    json.dumps({"items": items_all}, ensure_ascii=False, indent=1))
print("saved reviewer/out/_event_69289369.json", flush=True)