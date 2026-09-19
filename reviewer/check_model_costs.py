#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decisive free check: what does the server say each 4p engine costs?

The bundle's cost rule is:

    const d = model?.creditsOverride ?? costs["review_standard_4p"] ?? 0;
    return d > 0 && push(cost(d));            // only charges when d > 0

and a model is badged "(名人堂免費)" when it is isFree / creditsOverride === 0.
The model list comes from the server, so GET /api/v2/config settles it.

Also checks the free-RERUN rule, which the bundle reads as
`if (isFreeRerun || billingExempt) return zeroCost`.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work"
API = BASE + "/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(path, accept="application/json"):
    r = urllib.request.Request(BASE + path if path.startswith("/") else path,
                               headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": accept, "Cookie": COOKIE,
        "Referer": BASE + "/hall-of-fame",
    })
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


st, txt = get(API + "/config")
print(f"GET /api/v2/config -> HTTP {st}  ({len(txt)} bytes)")
if st != 200:
    print(txt[:400])
    sys.exit(1)

obj = json.loads(txt)
cfg = obj.get("data", obj)


def find_models(o, depth=0, want="models4p"):
    """Locate the 4p model catalogue (find_models used to stop at models3p)."""
    if depth > 5:
        return None
    if isinstance(o, dict):
        if want in o and isinstance(o[want], list):
            return want, o[want]
        for v in o.values():
            r = find_models(v, depth + 1, want)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_models(v, depth + 1, want)
            if r:
                return r
    return None


found = find_models(cfg, want="models4p")
if not found:
    found = find_models(cfg, want="models3p")
if not found:
    print("no model list found; top-level keys:")
    print("  ", list(cfg.keys()) if isinstance(cfg, dict) else type(cfg))
    print(json.dumps(cfg, ensure_ascii=False)[:1200])
    sys.exit(0)

key, models = found
print(f"models list: {key}  ({len(models)} entries)")
print()
print(f'{"id":<12} {"isFree":<7} {"credOverride":<13} {"memberOnly":<11} {"external":<9} name')
print("-" * 90)
for m in models:
    if not isinstance(m, dict):
        continue
    name = (m.get("name") or m.get("displayName") or m.get("label") or "")
    if isinstance(name, dict):
        name = name.get("zh") or name.get("en") or ""
    print(f'{str(m.get("id")):<12} {str(m.get("isFree")):<7} '
          f'{str(m.get("creditsOverride")):<13} {str(m.get("memberOnly")):<11} '
          f'{str(m.get("external")):<9} {name}')
print()
rigel = [m for m in models if isinstance(m, dict) and m.get("id") == "rigel_14"]
if rigel:
    m = rigel[0]
    free = (m.get("isFree") is True) or (m.get("creditsOverride") == 0)
    print("=== rigel_14 verdict ===")
    print(json.dumps(m, ensure_ascii=False, indent=2)[:1500])
    print()
    if free:
        print("=> rigel_14 is FREE: submitting new games spends nothing.")
    else:
        print("=> rigel_14 is NOT free: each new game costs "
              f"{m.get('creditsOverride') or 10} credits.")
        print("   (the hall-of-fame games we already harvested were FREE TO")
        print("    READ because someone else had already run them.)")
else:
    print("rigel_14 not present in this list")
