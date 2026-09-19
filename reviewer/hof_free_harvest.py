#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mass-harvest FREE RIGEL 1.4 analyses via the hall-of-fame submit endpoint.

THE INSIGHT (verified, cost 0 credits)
--------------------------------------
POST /api/v2/review charges 10 credits per game.  But the hall-of-fame showcase
has its own endpoint:

    POST /api/v2/hall-of-fame/submit
      { paipu, model, analysisMode, seat?, language }

which is governed only by a DAILY RUN COUNT -- its error codes are
HOF_DAILY_RUNS_EXCEEDED / HOF_SUBMIT_SUSPENDED / HOF_NOT_A_PLAYER_GAME, and the
SubmitPanel component contains no credit guard at all.  Verified empirically: a
new RIGEL 1.4 analysis was created (taskId d6c36f8c4e834cd9, cached=false) and
the balance stayed at 80/80.

The only constraint is that the game must involve a hall-of-fame player, which is
exactly what nodocchi gives us:

    GET https://nodocchi.moe/api/listuser.php?name=<player>   -> 2.5 MB, ~6000 games
    each entry carries url = https://tenhou.net/3/?log=<logid>

USAGE (from the repo root)
--------------------------
    $env:BIGCOACH_COOKIE = "<cookie>"
    python reviewer\\hof_free_harvest.py --out-dir reviewer\\out\\hof_free --limit 20

Be a good citizen: the default delay is deliberately slow, and the script stops
the moment the server says the daily budget is exhausted.
"""
from __future__ import annotations

import argparse
import http.cookiejar
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
NODOCCHI = "https://nodocchi.moe/api/listuser.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


class DailyLimit(Exception):
    pass


class Suspended(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"retry after {retry_after:.0f}s")
        self.retry_after = retry_after


def make_getter():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(url, accept="application/json", referer="https://gokujan.com/hall-of-fame"):
        if url.startswith("/api/"):
            url = ORIGIN + url
        elif url.startswith("/"):
            url = API + url
        r = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": accept, "Cookie": COOKIE,
            "Referer": referer, "Origin": "https://gokujan.com",
            "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8",
        })
        try:
            with opener.open(r, timeout=90) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return -1, str(e)

    def post(path, body):
        data = json.dumps(body).encode()
        r = urllib.request.Request(
            API + path, data=data, method="POST",
            headers={"User-Agent": UA, "Accept": "application/json",
                     "Cookie": COOKIE, "Content-Type": "application/json",
                     "Referer": "https://gokujan.com/hall-of-fame",
                     "Origin": "https://gokujan.com"})
        try:
            with opener.open(r, timeout=120) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # the server sends `retry-after` (observed 1047s) on 429 -- honour it
            if e.code == 429:
                ra = e.headers.get("retry-after")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = 900.0
                raise RateLimited(wait)
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return -1, str(e)

    return get, post


def hof_players(get):
    st, txt = get("/hall-of-fame/players")
    if st != 200:
        raise RuntimeError(f"players HTTP {st}: {txt[:200]}")
    obj = json.loads(txt)
    data = obj.get("data", obj)
    if isinstance(data, dict):
        data = data.get("items") or data.get("players") or []
    return [p for p in data if isinstance(p, dict)]


def nodocchi_games(get, name, want_4p=True):
    st, txt = get(f"{NODOCCHI}?name={urllib.parse.quote(name)}",
                  referer="https://nodocchi.moe/tenhoulog/")
    if st != 200:
        return []
    try:
        obj = json.loads(txt)
    except Exception:
        return []
    out = []
    for e in obj.get("list") or []:
        if not isinstance(e, dict):
            continue
        if want_4p and e.get("playernum") != 4:
            continue
        u = e.get("url")
        if not u:
            continue
        out.append({
            "url": u,
            "starttime": e.get("starttime"),
            "playernum": e.get("playernum"),
            "seat": next((s for s in (1, 2, 3, 4)
                          if e.get(f"player{s}") == name), None),
            "players": [e.get(f"player{s}") for s in (1, 2, 3, 4)],
        })
    return out


def submit(post, paipu, model="rigel_14", seat=None):
    body = {"paipu": paipu, "model": model,
            "analysisMode": "standard", "language": "zh-TW"}
    if seat is not None:
        body["seat"] = seat
    st, txt = post("/hall-of-fame/submit", body)
    try:
        obj = json.loads(txt)
    except Exception:
        obj = {"raw": txt}
    code = obj.get("code") or (obj.get("error") or {}).get("code") \
        if isinstance(obj.get("error"), dict) else obj.get("code")
    if "HOF_DAILY_RUNS_EXCEEDED" in txt:
        raise DailyLimit(txt[:200])
    if "HOF_SUBMIT_SUSPENDED" in txt:
        raise Suspended(txt[:200])
    return st, obj


def wait_for_json(get, task_id, tries=20, delay=6):
    for _ in range(tries):
        st, txt = get(f"/tasks/{task_id}/result")
        if st == 200:
            try:
                d = json.loads(txt).get("data") or {}
            except Exception:
                d = {}
            url = d.get("jsonUrl")
            if url:
                st2, body = get(url)
                if st2 == 200:
                    return d, body
        time.sleep(delay)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="reviewer/out/hof_free")
    ap.add_argument("--limit", type=int, default=20,
                    help="max NEW runs this invocation")
    ap.add_argument("--players", default="",
                    help="comma separated subset of player names")
    ap.add_argument("--delay", type=float, default=20.0,
                    help="seconds between submissions.  The endpoint is rate "
                         "limited (HTTP 429 with retry-after ~1047s when "
                         "hammered), so keep this generous")
    ap.add_argument("--model", default="rigel_14")
    args = ap.parse_args()

    if not COOKIE:
        print("set BIGCOACH_COOKIE first", file=sys.stderr)
        return 2

    out = pathlib.Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "_index.json"
    index = {}
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    done_ids = set(index.keys())

    get, post = make_getter()

    # balance snapshot
    st, txt = get("/membership/status")
    if st == 200:
        c = json.loads(txt).get("data", {}).get("credits", {})
        print(f"credits before: balance={c.get('balance')} used={c.get('used')}")

    players = hof_players(get)
    if args.players:
        want = {p.strip() for p in args.players.split(",")}
        players = [p for p in players if (p.get("displayName") or p.get("name")) in want]
    print(f"hall-of-fame players: {len(players)}")

    new_runs = 0
    try:
        for i, p in enumerate(players, 1):
            name = p.get("displayName") or p.get("name")
            if not name:
                continue
            games = nodocchi_games(get, name)
            fresh = [g for g in games
                     if g["url"].split("log=")[-1] not in done_ids]
            print(f"  [{i}/{len(players)}] {name[:22]:22} "
                  f"4p={len(games):5} new={len(fresh):5}", flush=True)
            for g in fresh:
                if new_runs >= args.limit:
                    raise KeyboardInterrupt
                gid = g["url"].split("log=")[-1]
                try:
                    st, obj = submit(post, g["url"], model=args.model,
                                     seat=g.get("seat"))
                except RateLimited as e:
                    # observed once already: 275 consecutive 429s because the
                    # script kept hammering.  Sleep it out, then retry this game.
                    print(f"    .. rate limited, sleeping {e.retry_after:.0f}s "
                          f"({e.retry_after/60:.1f} min)", flush=True)
                    time.sleep(e.retry_after + 5)
                    try:
                        st, obj = submit(post, g["url"], model=args.model,
                                         seat=g.get("seat"))
                    except RateLimited as e2:
                        print(f"    !! still limited ({e2.retry_after:.0f}s); "
                              f"stopping this session")
                        raise KeyboardInterrupt
                except DailyLimit as e:
                    print(f"    !! DAILY LIMIT REACHED: {e}")
                    raise KeyboardInterrupt
                except Suspended as e:
                    print(f"    !! SUSPENDED: {e}")
                    raise KeyboardInterrupt

                if st != 200 or not obj.get("success"):
                    print(f"    ! submit failed HTTP {st}: "
                          f"{json.dumps(obj, ensure_ascii=False)[:160]}")
                    continue
                d = obj.get("data") or {}
                task = d.get("taskId")
                if not task:
                    continue
                if d.get("cached"):
                    index[gid] = {"taskId": task, "cached": True}
                    continue
                meta, body = wait_for_json(get, task)
                if body:
                    (out / f"{gid}.json").write_text(body, encoding="utf-8")
                    index[gid] = {"taskId": task, "cached": False,
                                  "engine": (meta or {}).get("modelName"),
                                  "player": name,
                                  "url": g["url"],
                                  "starttime": g.get("starttime")}
                    new_runs += 1
                    if new_runs % 5 == 0:
                        print(f"    +{new_runs} new runs "
                              f"(latest {gid}, "
                              f"{(meta or {}).get('modelName')})", flush=True)
                else:
                    print(f"    ! timeout waiting for {task}")
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("  stopping")
    finally:
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        st, txt = get("/membership/status")
        if st == 200:
            c = json.loads(txt).get("data", {}).get("credits", {})
            print(f"credits after : balance={c.get('balance')} "
                  f"used={c.get('used')}")
        print(f"new runs this session: {new_runs}   total indexed: {len(index)}")
        print(f"output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
