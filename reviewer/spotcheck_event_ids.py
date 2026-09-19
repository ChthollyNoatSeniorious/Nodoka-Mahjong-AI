#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spot-check N event taskIds through the full public read API."""
import json
import pathlib
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
API = "https://review.bigcoach.work/api/v2"
ORIGIN = "https://review.bigcoach.work"

ids = [l.split()[0] for l in
       (HERE / "out" / "_event_taskids_new.txt").read_text(encoding="utf-8")
       .splitlines() if l.strip()][:5]

for rid in ids:
    try:
        r = urllib.request.Request(f"{API}/tasks/{rid}/result",
                                   headers={"User-Agent": UA,
                                            "Accept": "application/json"})
        with urllib.request.urlopen(r, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8", "replace"))
        d = res["data"]
        jurl = d.get("jsonUrl")
        if not jurl.startswith("http"):
            jurl = ORIGIN + jurl
        r2 = urllib.request.Request(jurl, headers={"User-Agent": UA,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(r2, timeout=120) as resp2:
            data = json.loads(resp2.read().decode("utf-8", "replace"))
        kyokus = data.get("review", {}).get("kyokus", [])
        entries = sum(len(k.get("entries", [])) for k in kyokus)
        mjai = len(data.get("mjai_log") or [])
        print(f"{rid} model={d.get('modelName')} n={d.get('nplayer')} "
              f"kyokus={len(kyokus)} entries={entries} mjai={mjai} "
              f"bytes={len(json.dumps(data, ensure_ascii=False))}", flush=True)
    except Exception as e:
        print(f"{rid} ERR {e}", flush=True)