#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bigcoach automated pipeline: login -> submit paipu -> track -> record.

Endpoints (reverse engineered from SPA bundle index-Cm5rmvvj.js):
    POST /api/v2/auth/login        {"email", "password"}  (session cookie)
    GET  /api/v2/membership/status (cookie) -> credits
    POST /api/v2/review            multipart:
        paipuId            (majsoul link or id, may include _key suffix)
        model4p            ("rigel_14" = 均衡型 1.4)
        analysisMode       ("standard")
        ui                 ("auto")
        language           ("zh")
    GET  /api/v2/tasks/<id>/progress
    GET  /api/v2/tasks/<id>/result  (public, no cookie)
    GET  <result.jsonUrl>           (public, full review JSON)

Credits: 10 per 4p review; 150 per account => 15 reviews per account.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ORIGIN = "https://review.bigcoach.work"
API = ORIGIN + "/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out" / "bigcoach_runs"
OUT.mkdir(parents=True, exist_ok=True)
STATE = OUT / "_state.json"
ID_RE = re.compile(r"([0-9a-f]{16})")


def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return op


def req(opener, method: str, path: str, body=None, multipart: dict | None = None,
        timeout: int = 180):
    url = path if path.startswith("http") else API + path
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Accept-Language": "zh-TW,zh;q=0.9",
               "Referer": ORIGIN + "/analyze"}
    data = None
    if multipart is not None:
        boundary = "----bc" + time.strftime("%H%M%S") + "x"
        parts = []
        for k, v in multipart.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                         f'name="{k}"\r\n\r\n{v}\r\n')
        parts.append(f"--{boundary}--\r\n")
        data = "".join(parts).encode("utf-8")
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def load_state(worker: int = 0) -> dict:
    files = [STATE]
    if worker > 0:
        files.append(OUT / f"_state_w{worker}.json")
    elif worker == 0:
        # resume mode: merge every worker's leftover state too
        files += sorted(OUT.glob("_state_w*.json"))
    merged = {"done": [], "results": []}
    for f in files:
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                merged["done"] += d.get("done", [])
                merged["results"] += d.get("results", [])
            except Exception:
                pass
    merged["done"] = sorted(set(merged["done"]))
    return merged


def save_state(st: dict, worker: int = 0):
    f = (OUT / f"_state_w{worker}.json") if worker > 0 else STATE
    f.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def login(opener, email: str, password: str) -> tuple[bool, str]:
    st, txt = req(opener, "POST", "/auth/login", {"email": email,
                                                  "password": password})
    if st == 200:
        return True, txt[:200]
    return False, f"HTTP {st} {txt[:200]}"


def get_credits(opener) -> int | None:
    st, txt = req(opener, "GET", "/membership/status")
    if st != 200:
        return None
    try:
        d = json.loads(txt).get("data") or {}
        c = d.get("credits")
        if isinstance(c, dict):
            return c.get("remaining") or c.get("total")
        return c
    except Exception:
        return None


def submit(opener, paipu: str, model: str = "rigel_14", player_id: int | None = None):
    """POST /review; returns (status, body, retry_after)."""
    mp = {"paipuId": paipu, "analysisMode": "standard", "ui": "auto",
          "language": "zh", "model4p": model}
    if player_id is not None:
        mp["playerId"] = str(player_id)
    url = API + "/review"
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Accept-Language": "zh-TW,zh;q=0.9",
               "Referer": ORIGIN + "/analyze"}
    boundary = "----bc" + time.strftime("%H%M%S") + "x"
    parts = []
    for k, v in mp.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"\r\n\r\n{v}\r\n')
    parts.append(f"--{boundary}--\r\n")
    data = "".join(parts).encode("utf-8")
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    r = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with opener.open(r, timeout=180) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), \
                resp.headers.get("Retry-After")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), \
            e.headers.get("Retry-After")


def wait_done(task_id: str, max_wait: int = 240) -> dict:
    """Poll progress until the review is finished. Returns status info."""
    t0 = time.time()
    last = {}
    while time.time() - t0 < max_wait:
        st, txt = req(None, "GET", f"/tasks/{task_id}/progress") if False else \
            req(urllib.request.build_opener(), "GET", f"/tasks/{task_id}/progress")
        try:
            last = json.loads(txt).get("data") or {}
        except Exception:
            last = {"raw": txt[:200]}
        s = str(last.get("status", "")).lower()
        if s in ("done", "finished", "success", "completed", "error", "failed"):
            return last
        time.sleep(4)
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", type=pathlib.Path,
                    default=HERE.parent / "Coach" / "bigcoach_account.txt")
    ap.add_argument("--paipus", type=pathlib.Path,
                    default=HERE / "out" / "player72520_paipus.txt")
    ap.add_argument("--email", help="single account email (login test)")
    ap.add_argument("--password", default=os.environ.get("BIGCOACH_PASSWORD", ""))
    ap.add_argument("--paipu", help="single paipu to submit (test)")
    ap.add_argument("--max-per-account", type=int, default=15)
    ap.add_argument("--submit-delay", type=float, default=9.0)
    ap.add_argument("--limit", type=int, help="max paipus to run overall")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--worker", type=int, default=0,
                    help="1-based worker index (accounts split round-robin)")
    args = ap.parse_args()

    # --- login test mode ---
    if args.email:
        op = make_opener()
        ok, msg = login(op, args.email, args.password)
        print(f"login {args.email}: {'OK' if ok else 'FAIL'} {msg}")
        if not ok:
            return 1
        if args.paipu:
            creds = get_credits(op)
            print("credits:", creds)
            st, txt, ra = submit(op, args.paipu)
            print("submit:", st, txt[:400], "retry-after:", ra)
            m = ID_RE.search(txt)
            if m:
                tid = m.group(1)
                info = wait_done(tid)
                print("final progress:", json.dumps(info, ensure_ascii=False)[:400])
        return 0

    # --- bulk mode ---
    accounts = [l.strip() for l in args.accounts.read_text(encoding="utf-8")
                .splitlines() if l.strip()]
    paipus = [l for l in args.paipus.read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.startswith("#")]
    workers = getattr(args, "workers", 1)
    worker = getattr(args, "worker", 0)
    print(f"accounts: {len(accounts)}, paipus: {len(paipus)}, "
          f"worker {worker}/{workers}")
    if args.limit:
        paipus = paipus[:args.limit]
    state = load_state(worker)
    done_keys = set(state.get("done", []))
    results = state.get("results", [])
    paipu_list = []
    for line in paipus:
        m = re.search(r"paipu=([A-Za-z0-9_.-]+)", line)
        if m:
            paipu_list.append(m.group(1))
    print(f"parsed paipus: {len(paipu_list)}")

    # account assignment: worker N handles accounts[N-1::M]
    my_accounts = []
    for ai, acct in enumerate(accounts):
        if workers > 1 and ai % workers != (worker - 1):
            continue
        my_accounts.append((ai, acct.split("|")[0].strip()))
    print(f"my accounts: {len(my_accounts)}", flush=True)

    n_done = 0
    n_fail = 0
    for ai, email in my_accounts:
        seg = paipu_list[ai * args.max_per_account:
                         (ai + 1) * args.max_per_account]
        acct_done = sum(1 for k in done_keys if k.startswith(email + "|"))
        todo = [pp for pp in seg
                if f"{email}|{pp}" not in done_keys]
        if not todo:
            print(f"[skip] {email} segment complete ({acct_done})", flush=True)
            continue
        op = make_opener()
        ok, msg = login(op, email, args.password)
        if not ok:
            print(f"[{ai}] {email} login FAIL: {msg[:120]}", flush=True)
            continue
        print(f"[{ai}] {email} logged in, segment {len(seg)} "
              f"todo {len(todo)}", flush=True)
        done = 0
        for paipu in todo:
            st = 0
            txt = ""
            for attempt in range(6):
                st, txt, ra = submit(op, paipu)
                if st == 429 and attempt < 5:
                    try:
                        ra_s = float(ra) if ra else 35.0
                    except (TypeError, ValueError):
                        ra_s = 35.0
                    ra_s = max(ra_s, 5.0) + 1.0
                    print(f"  429 on {paipu[:20]}... "
                          f"retry-after={ra} sleep {ra_s:.0f}s "
                          f"(attempt {attempt+1}/6)", flush=True)
                    time.sleep(ra_s)
                    continue
                break
            m2 = ID_RE.search(txt)
            if st != 200 or not m2:
                n_fail += 1
                print(f"  {email} submit FAIL {st}: {txt[:150]}", flush=True)
                results.append({"account": email, "paipu": paipu,
                                "status": f"submit HTTP {st}",
                                "detail": txt[:200]})
                save_state({"done": sorted(done_keys | {f"{email}|{paipu}"}),
                            "results": results}, worker)
                continue
            tid = m2.group(1)
            results.append({"account": email, "paipu": paipu, "taskId": tid,
                            "status": "submitted"})
            done_keys.add(f"{email}|{paipu}")
            done += 1
            n_done += 1
            if n_done % 5 == 0 or n_done <= 3:
                print(f"  W{worker} [{n_done}] {paipu[:24]}... task={tid}",
                      flush=True)
            save_state({"done": sorted(done_keys), "results": results}, worker)
            time.sleep(args.submit_delay)
    print(f"\nW{worker} finished. new runs: {n_done}, failures: {n_fail}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())