#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative rate experiment for the free hall-of-fame submit endpoint.

Two unknowns to measure:
  1. SUSTAINABLE RATE -- how often can we submit before HTTP 429?
     (one 429 already observed with retry-after: 1047s after a 2s-interval burst)
  2. TOTAL / DAILY CAP -- the user reports a hall-of-fame run limit of unknown
     size; the server signals it as HOF_DAILY_RUNS_EXCEEDED.

Method: submit one game at a time with a generous fixed gap, record every
response and header, sleep out any retry-after, and STOP immediately on any
cap/suspension signal.  Nothing is hammered.

Reads/writes reviewer/out/hof_free/ and its _index.json (dedup + resume).
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
NODOCCHI = "https://nodocchi.moe/api/listuser.php"


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
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, {}, str(e)


def limit_headers(hdrs):
    return {k: v for k, v in hdrs.items()
            if any(t in k.lower() for t in
                   ("rate", "retry", "limit", "remain", "reset", "quota"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="reviewer/out/hof_free")
    ap.add_argument("--limit", type=int, default=15, help="new runs this session")
    ap.add_argument("--delay", type=float, default=30.0,
                    help="seconds between submissions")
    ap.add_argument("--player", default="☆孫燕姿☆")
    ap.add_argument("--stop-on-429", action="store_true",
                    help="stop cleanly on the first 429 instead of sleeping it "
                         "out (gives a clean measurement of the per-window "
                         "budget)")
    args = ap.parse_args()

    out = pathlib.Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    idx_p = out / "_index.json"
    index = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.is_file() else {}
    done = set(index.keys())

    log = []
    t_start = time.time()

    def stamp(msg):
        el = time.time() - t_start
        line = f"[{el/60:6.1f}m] {msg}"
        print(line, flush=True)
        log.append(line)

    # ---- 1. is the cooldown over? ------------------------------------- #
    st, hdrs, txt = call("/membership/status")
    if st != 200:
        stamp(f"membership/status HTTP {st} -> API not usable yet: {txt[:160]}")
        return 1
    c = json.loads(txt).get("data", {}).get("credits", {})
    stamp(f"API reachable. credits balance={c.get('balance')} used={c.get('used')} "
          f"limit={c.get('limit')}")
    stamp(f"rate headers: {limit_headers(hdrs) or '(none)'}")

    # ---- 2. gather candidate paipu ------------------------------------ #
    st, _, txt = call(f"{NODOCCHI}?name={urllib.parse.quote(args.player)}")
    games = []
    if st == 200:
        for e in (json.loads(txt).get("list") or []):
            if not isinstance(e, dict) or e.get("playernum") != 4:
                continue
            u = e.get("url")
            if not u:
                continue
            gid = u.split("log=")[-1]
            if gid in done:
                continue
            # nodocchi numbers seats 1..4 while the API wants 0..3 -- sending
            # 1..4 made EVERY multi-HOF game fail with HOF_CHOOSE_SEAT (409),
            # and those failed calls still consume the rate budget
            seat = next((s - 1 for s in (1, 2, 3, 4)
                         if e.get(f"player{s}") == args.player), None)
            games.append({"gid": gid, "url": u, "seat": seat})
    stamp(f"player {args.player!r}: {len(games)} unseen 4p games available")
    if not games:
        return 0

    # ---- 3. paced submissions ----------------------------------------- #
    ok = 0
    cached = 0
    err = 0
    rate_events = []
    stop_reason = "reached --limit"

    def fetch_and_save(task, gid):
        for _ in range(6):
            time.sleep(6)
            s2, _, t2 = call(f"/tasks/{task}/result")
            if s2 != 200:
                continue
            ju = (json.loads(t2).get("data") or {}).get("jsonUrl")
            if not ju:
                continue
            s3, _, body = call(ju)
            if s3 == 200:
                (out / f"{gid}.json").write_text(body, encoding="utf-8")
                return True
        return False

    try:
        for g in games:
            if ok + cached >= args.limit:
                break
            t0 = time.time()
            st, hdrs, txt = call("/hall-of-fame/submit", {
                "paipu": g["url"], "model": "rigel_14",
                "analysisMode": "standard", "language": "zh-TW",
                "seat": g["seat"]}, method="POST")

            lh = limit_headers(hdrs)
            if st == 429:
                ra = hdrs.get("retry-after") or hdrs.get("Retry-After")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = 900.0
                rate_events.append({"at_run": ok + cached, "retry_after": wait,
                                    "headers": lh, "body": txt[:180]})
                stamp(f"429 RATE_LIMITED after {ok+cached} runs "
                      f"(retry-after={wait:.0f}s = {wait/60:.1f} min) "
                      f"headers={lh or '(none)'}")
                if args.stop_on_429:
                    stop_reason = (f"rate limited after {ok+cached} runs; "
                                   f"retry-after {wait:.0f}s")
                    break
                stamp(f"sleeping {wait:.0f}s ...")
                time.sleep(wait + 10)
                continue

            try:
                obj = json.loads(txt)
            except Exception:
                obj = {}
            code = (obj.get("error") or {}).get("code") if isinstance(
                obj.get("error"), dict) else obj.get("code")

            if code == "HOF_CHOOSE_SEAT" and obj.get("error", {}).get("details"):
                # the game has several HOF players; pick the first candidate
                cands = obj["error"]["details"].get("candidates") or []
                if cands:
                    st, hdrs, txt = call("/hall-of-fame/submit", {
                        "paipu": g["url"], "model": "rigel_14",
                        "analysisMode": "standard", "language": "zh-TW",
                        "seat": cands[0].get("seat")}, method="POST")
                    try:
                        obj = json.loads(txt)
                    except Exception:
                        obj = {}

            code = (obj.get("error") or {}).get("code") if isinstance(
                obj.get("error"), dict) else obj.get("code")
            if code == "HOF_DAILY_RUNS_EXCEEDED" or "DAILY_RUNS" in txt:
                stamp(f"*** TOTAL/DAILY CAP REACHED after {ok+cached} runs ***")
                stamp(f"    body: {txt[:300]}")
                stamp(f"    headers: {lh or '(none)'}")
                stop_reason = "daily/total cap"
                break
            if code == "HOF_SUBMIT_SUSPENDED" or "SUSPENDED" in txt:
                stamp(f"*** SUSPENDED *** body: {txt[:300]}")
                stop_reason = "suspended"
                break
            if code == "HOF_NOT_A_PLAYER_GAME":
                stamp(f"    not-a-player-game (seat {g['seat']}) {txt[:160]}")
                err += 1
                continue

            if st == 200 and obj.get("success"):
                d = obj.get("data") or {}
                task = d.get("taskId")
                if d.get("cached"):
                    cached += 1
                    stamp(f"    cached #{cached} task={task} -- fetching anyway")
                    fetched = fetch_and_save(task, g["gid"])
                    stamps = "saved" if fetched else "fetch failed"
                    stamp(f"      {stamps}")
                else:
                    ok += 1
                    stamp(f"OK run #{ok}  task={task}  gid={g['gid']}  "
                          f"({time.time()-t0:.1f}s)")
                    fetched = fetch_and_save(task, g["gid"])
                    if not fetched:
                        stamp(f"      warn: payload not fetched for {task}")
                index[g["gid"]] = {"taskId": task, "cached": d.get("cached"),
                                   "player": args.player, "url": g["url"]}
            else:
                err += 1
                stamp(f"    unexpected HTTP {st}: {txt[:180]}")

            idx_p.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            time.sleep(args.delay)
    except KeyboardInterrupt:
        stop_reason = "interrupted"

    idx_p.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    st, _, txt = call("/membership/status")
    if st == 200:
        c = json.loads(txt).get("data", {}).get("credits", {})
        stamp(f"credits after: balance={c.get('balance')} used={c.get('used')}")

    print()
    print("=" * 72)
    print("EXPERIMENT SUMMARY")
    print("=" * 72)
    print(f"  stop reason        : {stop_reason}")
    print(f"  new runs (free)    : {ok}")
    print(f"  already cached     : {cached}")
    print(f"  errors             : {err}")
    print(f"  delay used         : {args.delay}s")
    print(f"  wall clock         : {(time.time()-t_start)/60:.1f} min")
    if rate_events:
        print(f"  rate-limit events  : {len(rate_events)}")
        for e in rate_events:
            print(f"     after {e['at_run']} runs -> retry-after "
                  f"{e['retry_after']:.0f}s ({e['retry_after']/60:.1f} min)")
    else:
        print("  rate-limit events  : none  <- the pacing held")
    print(f"  total indexed      : {len(index)}")
    print(f"  output             : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
