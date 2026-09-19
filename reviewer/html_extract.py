#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract distillation-ready data from saved review HTML files.

The user saves each 極雀/Gokujan review page (review.bigcoach.work/review/<id>)
with SingleFile.  Each such HTML contains:

  * the review ID / engine chip (e.g. "RIGEL 1.4"),
  * four embedded tenhou.net/6 per-kyoku JSON logs (one <textarea> each),
  * one decision entry per reviewed player's turn, each with a full candidate
    table: action tile + pi_tau(a|s)*100 (sums to 100 -> complete support).

This script extracts all of that into reviewer/out/html_runs/<gid>.json
(structured, validated) and writes a combined full-game tenhou JSON per game
(reviewer/out/html_runs/<gid>/tenhou_full.json) that `mjai-reviewer --mjai-out`
can convert to mjai.

Usage:
    python html_extract.py <file.html> [<file.html> ...]
    python html_extract.py --dir <folder>            # every *.html in folder
    python html_extract.py --html-path <p> --gid 12d0efb1aa59fcd4
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out" / "html_runs"

URL_RE = re.compile(r"url:\s*(\S+)")
GID_RE = re.compile(r"review/([0-9a-f]{16})")
ENGINE_RE = re.compile(r"RIGEL\s*[\d.]+")
SAVED_RE = re.compile(r"saved date:\s*([^\n]+)")

TEXTAREA_RE = re.compile(r"<textarea[^>]*>(.*?)</textarea>", re.S)
ENTRY_SPLIT_RE = re.compile(r'<details class="?collapse entry')
SUMMARY_RE = re.compile(r"<summary>([^<]*)")
TURN_INFO_RE = re.compile(r"<span class=turn-info>([^<]*)")
ORDER_LOSS_RE = re.compile(r"#(\d+)\s*</span>/(\d+)")
TEHAI_RE = re.compile(
    r'<ul class=tehai-state>(.*?)</ul>', re.S
)
ROLE_RE = re.compile(r'<span class=role>([^<]*)</span>\s*([^<]*)')
ROW_RE = re.compile(
    r"<tr><td>(.*?)<td>\s*<span class=int>([\d.]+)</span><span class=frac>(\d+)</span>",
    re.S,
)
TILE_RE = re.compile(r"href=#pai-([a-z0-9]+)")

# Naki marker orders (from convlog): which byte pair is the original tile.
NAKI_ORD = {
    "c": (1, [3, 5]),  # chi      len 7 : pai at [1..3], consumed [3..5],[5..7]
    "p": (1, [3, 5]),  # pon      len 7 : pai at [1..3] when idx==0 …
    "m": (1, [3, 5]),  # daiminkan len 9
    "k": (1, [3, 5]),  # kakan    len 9
    "a": (7, [0, 2]),  # ankan    len 9 : pai at [7..9]
    "r": (1, None),    # reach    len 3 : pai at [1..3] (may be "60")
}


def parse_html(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    # SingleFile escapes the inlined classic page's quotes as &quot;.
    text = text.replace("&quot;", '"')
    out = {"source": str(path), "bytes": len(raw)}

    m = URL_RE.search(text)
    out["url"] = m.group(1) if m else None
    gid = None
    if out["url"]:
        gm = GID_RE.search(out["url"])
        if gm:
            gid = gm.group(1)
    if not gid:
        gm = GID_RE.search(text)
        if gm:
            gid = gm.group(1)
    out["gid"] = gid

    me = ENGINE_RE.search(text)
    out["engine"] = me.group(0) if me else None
    ms = SAVED_RE.search(text)
    out["saved_date"] = ms.group(1).strip() if ms else None

    # ---- per-kyoku raw logs ---------------------------------------------- #
    textareas = TEXTAREA_RE.findall(text)
    logs = []
    for ta in textareas:
        s = html_mod.unescape(ta).strip()
        if not (s.startswith("{") or s.startswith("[")):
            continue  # not a JSON log textarea
        try:
            logs.append(json.loads(s))
        except json.JSONDecodeError as exc:
            out.setdefault("warnings", []).append(f"json decode failed: {exc}")
    out["kyoku_logs_raw"] = logs
    out["n_kyoku"] = len(logs)

    # ---- entries ---------------------------------------------------------- #
    entries = []
    for chunk in ENTRY_SPLIT_RE.split(text)[1:]:
        mark_red = bool(re.search(r"data-mark-red", chunk))
        ent = {"mark_red": mark_red}

        sm = SUMMARY_RE.search(chunk)
        ent["summary"] = sm.group(1).strip() if sm else None
        tm = TURN_INFO_RE.search(chunk)
        ent["turn_info"] = tm.group(1).strip() if tm else None
        om = ORDER_LOSS_RE.search(chunk)
        if om:
            ent["rank"] = int(om.group(1))
            ent["n_candidates"] = int(om.group(2))

        # order-loss is the last span in turn-info; the leading part is shanten
        if ent.get("turn_info"):
            body = ent["turn_info"].replace("\xa0", " ").strip()
            ent["shanten_text"] = body

        th = TEHAI_RE.search(chunk)
        if th:
            ent["hand"] = TILE_RE.findall(th.group(1))

        roles = []
        for rtext, rval in ROLE_RE.findall(chunk):
            roles.append({"label": rtext.strip(), "value": rval.strip()})
        ent["roles"] = roles

        cands = []
        for content, intp, frac in ROW_RE.findall(chunk):
            prob = float(intp) + float(frac) / (10 ** len(frac))
            tiles = TILE_RE.findall(content)
            text = re.sub(r"<[^>]+>", "", content)
            text = html_mod.unescape(text).strip()
            cands.append(
                {
                    "tile": tiles[0] if tiles else None,
                    "tiles": tiles,
                    "label": text,
                    "prob": prob,
                }
            )
        ent["candidates"] = cands
        if cands:
            ent["prob_sum"] = round(sum(c["prob"] for c in cands), 4)
            ent["prob_sum_ok"] = abs(ent["prob_sum"] - 100.0) <= 2.0
        entries.append(ent)

    out["entries"] = entries
    out["n_entries"] = len(entries)
    out.setdefault("warnings", [])
    if len(logs) != 4:
        out["warnings"].append(f"expected 4 kyoku logs, got {len(logs)}")
    return out


def write_full_log(parsed: dict, dest_dir: Path) -> Path | None:
    """Combine the per-kyoku logs into one full-game RawLog JSON.

    Each embedded textarea carries the full tenhou.net/6 object (`dan`,
    `name`, `rule`, ...) whose `log` field holds *one* kyoku tuple; we keep
    the metadata of the first one and concatenate the kyoku tuples.
    """
    logs = parsed.get("kyoku_logs_raw") or []
    if not logs:
        return None
    head = dict(logs[0])
    head["log"] = [k["log"][0] for k in logs if isinstance(k.get("log"), list)]
    if not head["log"]:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "tenhou_full.json"
    out.write_text(json.dumps(head, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="saved review .html file(s)")
    ap.add_argument("--dir", help="process every *.html under this folder")
    args = ap.parse_args()

    files: list[Path] = [Path(p) for p in args.files]
    if args.dir:
        files += sorted(Path(args.dir).glob("*.html"))
    if not files:
        print("no input files", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_path = OUT_DIR / "_index.json"
    index = {}
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))

    summary_stats = []
    for path in files:
        parsed = parse_html(path)
        gid = parsed.get("gid")
        if not gid:
            print(f"[skip] no review id found in {path.name}")
            continue
        out_path = OUT_DIR / f"{gid}.json"
        out_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        full = write_full_log(parsed, OUT_DIR / gid)
        index[gid] = {
            "url": parsed.get("url"),
            "engine": parsed.get("engine"),
            "saved_date": parsed.get("saved_date"),
            "n_kyoku": parsed.get("n_kyoku"),
            "n_entries": parsed.get("n_entries"),
            "warnings": parsed.get("warnings", []),
            "tenhou_full": str(full) if full else None,
            "source": str(path),
        }
        ok_counts = sum(1 for e in parsed["entries"] if e.get("prob_sum_ok"))
        summary_stats.append(
            f"{gid}: {parsed.get('n_kyoku')} kyoku, {parsed.get('n_entries')} "
            f"entries, prob_sum_ok {ok_counts}/{parsed.get('n_entries')}, "
            f"engine={parsed.get('engine')}"
        )
        print(summary_stats[-1])

    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[index] {len(index)} games -> {index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())