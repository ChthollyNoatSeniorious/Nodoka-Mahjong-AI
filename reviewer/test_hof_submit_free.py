#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-risk probe of the hall-of-fame submit endpoint.

From SubmitPanel:
    mutationFn: a => POST /hall-of-fame/submit {
        paipu, model, compare, analysisMode, seat: a.seat, language }

and the form's FIRST call is `c.mutate({})` -- i.e. NO seat.  The server answers
with error code HOF_CHOOSE_SEAT, which the UI catches in onError to render a seat
picker.  Because it is an error path, no analysis run is started, so this call
cannot spend anything.

This script therefore:
  1. records the credit balance,
  2. posts a game WITHOUT a seat,
  3. records the balance again.

If the balance is unchanged and the reply is HOF_CHOOSE_SEAT, we have proved
the endpoint is reachable and free at this step.  Nothing else is submitted.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")

# a 4-player game of a hall-of-fame player (☆孫燕姿☆), from nodocchi
PAIPU = "https://tenhou.net/3/?log=2020100913gm-0041-0000-388c8bcb"
MODEL = "rigel_14"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
         "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame",
         "Origin": "https://gokujan.com"}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(API + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def balance():
    st, txt = call("/membership/status")
    if st != 200:
        return None
    d = json.loads(txt).get("data", {})
    c = d.get("credits", {})
    return c.get("balance"), c.get("used")


if not COOKIE:
    print("set BIGCOACH_COOKIE first")
    sys.exit(2)

print("=" * 72)
print("1. balance BEFORE")
print("=" * 72)
b0 = balance()
print(f"   balance={b0[0]}  used={b0[1]}")
print()

print("=" * 72)
print("2. POST /hall-of-fame/submit  WITHOUT a seat (error path, no run)")
print("=" * 72)
print(f"   paipu = {PAIPU}")
print(f"   model = {MODEL}")
print()
st, txt = call("/hall-of-fame/submit", "POST", {
    "paipu": PAIPU,
    "model": MODEL,
    "analysisMode": "standard",
    "language": "zh-TW",
})
print(f"   HTTP {st}")
try:
    obj = json.loads(txt)
    print("   response:")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:1800])
except Exception:
    print("   raw:", txt[:900])
print()

print("=" * 72)
print("3. balance AFTER")
print("=" * 72)
b1 = balance()
print(f"   balance={b1[0]}  used={b1[1]}")
print()
if b0[0] is not None and b1[0] is not None:
    if b1[0] < b0[0]:
        print(f"   *** BALANCE DROPPED by {b0[0]-b1[0]} -- it DOES charge. ***")
    else:
        print("   balance unchanged -> this step is free.")
print()
print("Nothing was run: no seat was supplied, so no analysis was started.")
