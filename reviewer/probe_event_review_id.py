#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check whether gokujan event review ids are bigcoach taskIds:
GET review.bigcoach.work/api/v2/tasks/<id>/result (public, no cookie)."""
import json
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
API = "https://review.bigcoach.work/api/v2"

for rid in ["5aaabe1a5fd507c3"]:
    r = urllib.request.Request(f"{API}/tasks/{rid}/result",
                               headers={"User-Agent": UA,
                                        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
        print(rid, "HTTP", resp.status, "len", len(body))
        d = json.loads(body)
        data = d.get("data") or {}
        print("  modelName:", data.get("modelName"))
        print("  nplayer:", data.get("nplayer"))
        print("  jsonUrl:", str(data.get("jsonUrl"))[:120])
        print("  paipuInfo:", str(data.get("paipuInfo"))[:200])
    except urllib.error.HTTPError as e:
        print(rid, "HTTP", e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print(rid, "ERR", e)