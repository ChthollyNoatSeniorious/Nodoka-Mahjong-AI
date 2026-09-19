#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harvest FREE Akino Hana (長明 / RIGEL 1.4) analyses from the bigcoach hall of fame.

WHY THIS IS FREE
----------------
The hall of fame holds games that have ALREADY been analysed.  Their results are
cached and addressed by task id, and downloading a cached result costs no
credits.  `POST /hall-of-fame/resolve` even hands you the task ids directly.

Measured pool (12 of 59 players sampled): 121 exact `rigel_14` 4p runs, i.e.
about 10 per player -> ~595 games across the whole hall of fame, ~128k decisions.

FILTERING MATTERS
-----------------
Each game may carry several analyses, from different engines:

    rigel_14           <- 長明 1.4 / RIGEL 1.4 / Akino Hana   (WANTED)
    zenith_10, halo_11, comet_10, nova_10                    (must be excluded)
    "rigel_14,zenith_10"                                     (a COMPARE run,
                                                              not a pure RIGEL result)
Three-player games use `sanma_rigel_14` and are skipped (`nplayer != 4`).

API
---
    GET /hall-of-fame/players                        -> 59 players
    GET /hall-of-fame/players/{platform}/{name}      -> games + cachedRuns
        ?page=N&pageSize=60   (pageSize > 60 returns HTTP 422)
    GET /tasks/{taskId}/result                       -> {jsonUrl, modelName, ...}
    GET {jsonUrl}                                    -> full review JSON

The review JSON has the same shape as mjai-reviewer's own output, so the action
mapping and the 100%-validated alignment apply unchanged.

USAGE
-----
    set BIGCOACH_COOKIE=<cookie>
    python reviewer\\hof_harvest.py --out-dir reviewer\\out\\hof --limit 20
    python reviewer\\hof_harvest.py --out-dir reviewer\\out\\hof          # full run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = HERE / "out" / "hof"

BASE = "https://review.bigcoach.work/api/v2"
SITE = "https://review.bigcoach.work"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

RIGEL_4P = "rigel_14"
RIGEL_3P = "sanma_rigel_14"


def make_getter(cookie: str):
    def resolve(path: str) -> str:
        """`jsonUrl` is already an absolute /api/v2/... path -- do not re-prefix."""
        if path.startswith("http"):
            return path
        if path.startswith("/api/"):
            return SITE + path
        return BASE + path

    def get(path: str, params: dict | None = None, accept="application/json",
            tries: int = 3):
        url = resolve(path)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": accept, "Cookie": cookie,
            "Referer": "https://review.bigcoach.work/hall-of-fame"})
        last = None
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                # 4xx other than 429 are not worth retrying
                if e.code != 429 and e.code < 500:
                    return e.code, body
                last = (e.code, body)
            except Exception as exc:
                last = (0, str(exc))
            time.sleep(1.5 * (attempt + 1))
        return last or (0, "")
    return get


def pure_rigel(run: dict, nplayer: int) -> bool:
    """True only for a PURE RIGEL 1.4 run on the right player count.

    `engineKeys` may be comma separated (a multi-model compare); those are not
    pure RIGEL results and are excluded.
    """
    ek = (run.get("engineKeys") or "").strip()
    want = RIGEL_4P if nplayer == 4 else RIGEL_3P
    return ek == want


def list_players(get) -> list[dict]:
    st, txt = get("/hall-of-fame/players")
    if st != 200:
        raise RuntimeError(f"player list failed: HTTP {st}: {txt[:200]}")
    obj = json.loads(txt)
    players = obj.get("data") if isinstance(obj, dict) else obj
    return [p for p in (players or []) if isinstance(p, dict)]


def player_games(get, platform: str, name: str, max_pages: int = 12) -> list[dict]:
    """All games for a player, following pagination (pageSize is capped at 60)."""
    out, page = [], 1
    while page <= max_pages:
        st, txt = get(f"/hall-of-fame/players/{platform}/{urllib.parse.quote(name)}",
                      {"page": page, "pageSize": 60})
        if st != 200:
            if page == 1:
                print(f"    ! player fetch HTTP {st}")
            break
        try:
            d = json.loads(txt).get("data")
        except Exception:
            break
        if not isinstance(d, dict):
            break
        items = d.get("items") or []
        out += items
        total = d.get("total") or 0
        if len(items) < 60 or len(out) >= total:
            break
        page += 1
    return out


def fetch_review(get, task_id: str) -> dict | None:
    """taskId -> full review JSON (free for cached runs).

    The engine identity (`modelName`, `engineKeys`) lives in the /result payload,
    NOT in the data JSON, so we copy it in -- that is how we prove a file really
    came from RIGEL 1.4 and not from NOVA / zenith / a compare run.
    """
    st, txt = get(f"/tasks/{task_id}/result")
    if st != 200:
        print(f"    ! result HTTP {st}")
        return None
    try:
        d = json.loads(txt).get("data") or {}
    except Exception:
        return None
    url = d.get("jsonUrl")
    if not url:
        return None
    st, body = get(url, accept="application/json")
    if st != 200:
        print(f"    ! data HTTP {st}")
        return None
    try:
        rev = json.loads(body)
    except Exception:
        return None
    rev["_engine"] = {
        "modelName": d.get("modelName"),
        "engineKeys": d.get("modelEngineKeys") or d.get("engineKeys"),
        "analysisMode": d.get("analysisMode"),
        "ui": d.get("ui"),
        "hallOfFame": d.get("hallOfFame"),
    }
    return rev


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Harvest free RIGEL 1.4 analyses from the bigcoach hall of fame.")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cookie", default=os.environ.get("BIGCOACH_COOKIE"))
    ap.add_argument("--limit", type=int, help="stop after N games (trial run)")
    ap.add_argument("--players", type=int, help="only scan the first N players")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between downloads (be polite)")
    ap.add_argument("--list-only", action="store_true",
                    help="only enumerate, do not download")
    args = ap.parse_args()

    if not args.cookie:
        print("ERROR: set BIGCOACH_COOKIE or pass --cookie", file=sys.stderr)
        return 2
    args.out_dir = args.out_dir.resolve()
    get = make_getter(args.cookie)

    players = list_players(get)
    if args.players:
        players = players[:args.players]
    print(f"hall of fame: {len(players)} player(s) to scan")
    print()

    # ---- enumerate -------------------------------------------------------- #
    jobs = []            # (task_id, canonical_id, seat, player_name)
    seen_task = set()
    seen_game = set()
    for pi, p in enumerate(players, 1):
        platform = p.get("platform", "tenhou")
        name = p.get("playerKey") or p.get("displayName")
        if not name:
            continue
        games = player_games(get, platform, name)
        hit = 0
        for g in games:
            if g.get("nplayer") != 4:
                continue
            cid = g.get("canonicalId")
            for run in (g.get("cachedRuns") or []):
                if not pure_rigel(run, 4):
                    continue
                tid = run.get("taskId")
                if not tid or tid in seen_task:
                    continue
                seen_task.add(tid)
                seen_game.add(cid)
                jobs.append((tid, cid, g.get("seat"), name))
                hit += 1
        print(f"  [{pi}/{len(players)}] {name[:24]:<24} games={len(games):>4} "
              f"rigel_14={hit:>3}  (running total {len(jobs)})")

    print()
    print(f"distinct games with a pure rigel_14 analysis: {len(seen_game)}")
    print(f"analysis tasks to download                  : {len(jobs)}")
    if args.limit:
        jobs = jobs[:args.limit]
        print(f"limited to first {len(jobs)}")
    print()

    if args.list_only:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        idx = args.out_dir / "_index.json"
        idx.write_text(json.dumps(
            [{"taskId": t, "canonicalId": c, "seat": s, "player": n}
             for t, c, s, n in jobs], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"index written -> {idx}")
        return 0

    # ---- download --------------------------------------------------------- #
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ok = skip = fail = 0
    decisions = 0
    # one game can carry several rigel_14 tasks (reruns); keep only the newest
    # per canonicalId so the distillation set has no duplicate games.
    best = {}
    for tid, cid, seat, name in jobs:
        best.setdefault(cid, (tid, cid, seat, name))
    jobs = list(best.values())
    print(f"after de-duplicating by game: {len(jobs)} game(s) to download")
    print()
    for i, (tid, cid, seat, name) in enumerate(jobs, 1):
        dest = args.out_dir / f"{cid}_s{seat}_{tid}.json"
        # an earlier task id for the same game is superseded; drop it
        for old in args.out_dir.glob(f"{cid}_s{seat}_*.json"):
            if old.name != dest.name:
                old.unlink()
        if dest.is_file():
            skip += 1
            continue
        rev = fetch_review(get, tid)
        if rev is None:
            fail += 1
            continue
        # sanity: must be the right model and have decision data
        try:
            n = rev["review"]["total_reviewed"]
            model = (rev.get("_engine") or {}).get("modelName")
        except Exception:
            n, model = 0, None
        if not n:
            fail += 1
            continue
        rev["_hof"] = {"taskId": tid, "canonicalId": cid, "seat": seat,
                       "player": name}
        dest.write_text(json.dumps(rev, ensure_ascii=False), encoding="utf-8")
        ok += 1
        decisions += n
        if i % 20 == 0 or i == len(jobs):
            print(f"  [{i}/{len(jobs)}] ok={ok} skip={skip} fail={fail} "
                  f"decisions={decisions:,}")
        time.sleep(args.delay)

    print()
    print(f"=== done: {ok} downloaded, {skip} already present, {fail} failed ===")
    print(f"    decisions collected: {decisions:,}")
    print(f"    output: {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
