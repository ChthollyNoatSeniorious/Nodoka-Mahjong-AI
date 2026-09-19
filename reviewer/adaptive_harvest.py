#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adaptive-cadence free harvest (v2).

The batch mode measured a per-window budget that shrank 7 -> 5 -> 4 -> 0 runs,
so a fixed batch size keeps hitting 429s at the START of a batch (wasted calls)
or over-shooting (wasted cooldown).  This version submits ONE game at a time and
adapts:

    on success : sleep --gap (default 300s)
    on 429     : sleep EXACTLY retry-after, then continue
    on cap     : stop and report the total

It also polls task results far less aggressively (every 15s, max 5) because the
earlier 6s-polling may have counted toward the same API budget.

    $env:BIGCOACH_COOKIE=...; python reviewer\\adaptive_harvest.py --target 300
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ORIGIN = "https://review.bigcoach.work"
API = ORIGIN + "/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
PLAYER = "☆孫燕姿☆"


def call(url, body=None, method="GET"):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
         "Referer": "https://gokujan.com/hall-of-fame",
         "Origin": "https://gokujan.com"}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


class StopHarvest(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--gap", type=float, default=300.0,
                    help="seconds to rest after each success (default 5 min)")
    ap.add_argument("--out-dir", default="reviewer/out/hof_free")
    args = ap.parse_args()

    out = pathlib.Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    idx_p = out / "_index.json"
    index = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.is_file() else {}
    done = set(index.keys())

    start = time.time()
    ok = 0
    cached = 0
    rate_events = []
    last_run_time = 0.0
    consecutive_429 = 0

    def now():
        return time.strftime("%H:%M:%S")

    def fetch(task, gid):
        for _ in range(5):
            time.sleep(15)
            s2, t2 = call(f"/tasks/{task}/result")
            if s2 != 200:
                continue
            d = json.loads(t2).get("data") or {}
            ju = d.get("jsonUrl")
            if not ju:
                continue
            s3, body = call(ju)
            if s3 == 200:
                (out / f"{gid}.json").write_text(body, encoding="utf-8")
                return True
        return False

    def next_game():
        st, txt = call(f"https://nodocchi.moe/api/listuser.php?name="
                       f"{urllib.parse.quote(PLAYER)}")
        if st != 200:
            return None
        try:
            lst = json.loads(txt).get("list") or []
        except Exception:
            return None
        for e in lst:
            if not isinstance(e, dict) or e.get("playernum") != 4:
                continue
            u = e.get("url")
            if not u:
                continue
            gid = u.split("log=")[-1]
            if gid in done:
                continue
            seat = next((s - 1 for s in (1, 2, 3, 4)
                         if e.get(f"player{s}") == PLAYER), None)
            return {"gid": gid, "url": u, "seat": seat}
        return None

    print(f"adaptive_harvest: target={args.target} gap={args.gap}s "
          f"started {time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"(indexed {len(index)})", flush=True)

    try:
        while True:
            # ---- pace: respect a minimum gap between submissions ---------
            since = time.time() - last_run_time
            if since < args.gap:
                time.sleep(args.gap - since)

            g = next_game()
            if g is None:
                print(f"[{now()}] no unseen games left; stopping", flush=True)
                break

            st, txt = call("/hall-of-fame/submit", {
                "paipu": g["url"], "model": "rigel_14",
                "analysisMode": "standard", "language": "zh-TW",
                "seat": g["seat"]}, method="POST")
            last_run_time = time.time()

            try:
                obj = json.loads(txt)
            except Exception:
                obj = {}
            code = (obj.get("error") or {}).get("code") if isinstance(
                obj.get("error"), dict) else obj.get("code")

            if st == 429:
                wait = 900.0
                if "retry-after" in txt.lower() or "retry_after" in txt.lower():
                    import re
                    m = re.search(r"retry[_-]?after[^\d]*(\d+)", txt, re.I)
                    if m:
                        wait = float(m.group(1))
                consecutive_429 += 1
                rate_events.append((time.strftime("%H:%M:%S"), wait))
                print(f"[{now()}] 429 after {ok} runs (x{consecutive_429}), "
                      f"retry-after={wait:.0f}s ({wait/60:.1f} min)",
                      flush=True)
                # The daily cap is a HARD quota: 2026-09-18 21:05 then 21:20
                # both 429 after 900s, and the 2026-09-19 00:35 midnight probe
                # hit the same wall (5 submits then 429, retry 900s later
                # still 429).  There is NO reset at 00:00 local time; the
                # limit is a sliding window (~1-5 submits per ~15 min, bucket
                # drains as the day goes on).  Sleeping and retrying in a
                # loop wastes nothing but also fixes nothing -- stop after
                # TWO consecutive 429s; use a long --gap for a slow trickle.
                if consecutive_429 >= 2:
                    raise StopHarvest(
                        f"DAILY_QUOTA two consecutive 429s after {ok} runs "
                        f"(last retry-after {wait:.0f}s); "
                        f"{len(index)} games indexed")
                time.sleep(wait)
                continue

            consecutive_429 = 0

            if "HOF_DAILY_RUNS_EXCEEDED" in txt:
                raise StopHarvest(f"daily/total cap at {ok} runs this session, "
                                  f"{len(index)} total (body: {txt[:200]})")
            if "HOF_SUBMIT_SUSPENDED" in txt:
                raise StopHarvest(f"suspended (body: {txt[:200]})")
            if code == "HOF_CHOOSE_SEAT":
                cands = (obj.get("error") or {}).get("details", {}).get(
                    "candidates") or []
                if not cands:
                    print(f"[{now()}] HOF_CHOOSE_SEAT with no candidates: "
                          f"{txt[:160]}", flush=True)
                    continue
                seat = cands[0].get("seat")
                st, txt = call("/hall-of-fame/submit", {
                    "paipu": g["url"], "model": "rigel_14",
                    "analysisMode": "standard", "language": "zh-TW",
                    "seat": seat}, method="POST")
                try:
                    obj = json.loads(txt)
                except Exception:
                    obj = {}
            if code == "HOF_NOT_A_PLAYER_GAME":
                print(f"[{now()}] not a player game: {txt[:120]}", flush=True)
                continue

            if st == 200 and obj.get("success"):
                d = obj.get("data") or {}
                task = d.get("taskId")
                if d.get("cached"):
                    cached += 1
                    fetched = fetch(task, g["gid"])
                    print(f"[{now()}] cached #{cached} ({g['gid']}) "
                          f"{'saved' if fetched else 'fetch failed'}", flush=True)
                else:
                    ok += 1
                    fetched = fetch(task, g["gid"])
                    print(f"[{now()}] run #{ok} ({g['gid']}, "
                          f"{'saved' if fetched else 'fetch PENDING'}) "
                          f"total={len(index)+ok}", flush=True)
                index[g["gid"]] = {"taskId": task, "cached": d.get("cached"),
                                   "player": PLAYER, "url": g["url"]}
                idx_p.write_text(
                    json.dumps(index, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                if not fetched:
                    index[g["gid"]]["fetch_pending"] = True
                    idx_p.write_text(
                        json.dumps(index, ensure_ascii=False, indent=1),
                        encoding="utf-8")
            else:
                print(f"[{now()}] HTTP {st}: {txt[:160]}", flush=True)

            if ok + cached >= args.target:
                raise StopHarvest(f"target reached: {ok} new + {cached} cached")
    except StopHarvest as e:
        print(f"\n*** STOPPED: {e.reason}", flush=True)
    except KeyboardInterrupt:
        print("\n*** interrupted by user", flush=True)
    finally:
        idx_p.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        hrs = (time.time() - start) / 3600
        print(f"summary: {ok} new + {cached} cached in {hrs:.2f}h "
              f"({ok/max(hrs,1e-9):.1f}/h); total indexed {len(index)}; "
              f"rate events: {len(rate_events)}", flush=True)
        for t, w in rate_events[-6:]:
            print(f"    {t} retry-after {w:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())