#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decision-level comparison on test03 between our checkpoints and Akino Hana.

`Test set/test03_*.htm` is the **Akino Hana / bigcoach "Coach" report** for that
game (seat tw=0). Its markup contains, for every one of the 216 reviewed
decisions:

    <details class="collapse entry">
      <summary>N巡 (余M) ... k向听  [<span class="order-loss">#r</span>/c]</summary>
      <ul class="tehai-state"> ... hand, tsumo tile ... </ul>
      <span class="role">玩家: </span> 打 <tile>            <- what the human played
      <span class="role">Coach: </span> 打 <tile>           <- Akino Hana's top-1
      <table class="data"> ... pi_tau values for every candidate ... </table>
    </details>

A red `order-loss #r/c` means the human's action was only rank *r* of *c*
candidates according to Akino Hana -- i.e. a disagreement.  Counting those
reproduces the 167/216 = 77.3% encoded in the filename, which validates the
parser.

The same decisions are present in our own `reviewer/out/testset/test03_*.json`
reports (`review.review.kyokus[*].entries[*]` with `actual` / `expected` /
`is_equal`), so the two can be aligned one-to-one and compared directly:

  * agreement of each model with the human,
  * **top-1 agreement between our model and Akino Hana** (the real style-fit
    number on this game, independent of how the human played),
  * how the two models split when they disagree with each other.

Usage (from the repo root):

    python reviewer\\compare_test03.py [--markdown out.md]
"""

from __future__ import annotations

import argparse
import collections
import html as htmllib
import json
import re
import sys
from pathlib import Path

# the console on zh-TW/zh-CN Windows is cp950/cp936 and cannot encode every
# Chinese verb that appears in the report; force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TESTSET = ROOT / "Test set"
JSON_DIR = HERE / "out" / "testset"
TAG = "test03"

# --------------------------------------------------------------------------- #
# 1. parse the Akino Hana report
# --------------------------------------------------------------------------- #
TILE_RE = re.compile(r'href="#pai-([0-9a-z_]+)"')
ENTRY_RE = re.compile(r'<details class="collapse entry"[^>]*>(.*?)(?=</details></details>|\Z)',
                      re.S)
ROW_RE = re.compile(
    r"<tr><td>(.*?)</td><td>\s*<span class=\"int\">(\d+)\.</span>"
    r"<span class=\"frac\">(\d+)</span></td></tr>", re.S)
JUNME_RE = re.compile(r"(\d+)巡 \(余(\d+)\)")
SHANTEN_RE = re.compile(r"(\d)向听")
LOSS_RE = re.compile(r'<span class="order-loss">\s*#(\d+)</span>/(\d+)')

VERB_MAP = {
    "打": "dahai",
    "摸切": "dahai",
    "碰": "pon",
    "吃": "chi",
    "杠": "kan",
    "明杠": "kan",
    "暗杠": "kan",
    "加杠": "kan",
    "立直": "reach",
    "和了": "hora",
    "和": "hora",
    "自摸": "hora",
    "拔北": "dahai",
    "荣和": "hora",
    "跳过": "none",
    "过": "none",
}


def norm_tile(t: str) -> str:
    """The report writes honours lowercase (`pai-w`); mjai uses `W`."""
    if not t:
        return t
    # numbered suits keep their case (`1s`), bare letters are honours
    return t if t[0].isdigit() else t.upper()


def cmp_key(key: str) -> str:
    """Comparison key.

    Discards are compared tile-by-tile (`dahai:1s`).  For calls / riichi the two
    renderers describe the same choice with different amounts of detail (the
    report prints the consumed tiles, we print the called tile), so those are
    compared by action type only -- they are ~7 of the 216 decisions.
    """
    return key if key.startswith("dahai:") else key.split(":", 1)[0]


def parse_action(cell: str) -> tuple[str, str, list[str]]:
    """(verb, canonical_key, tiles) for one action cell / role span."""
    text = htmllib.unescape(re.sub(r"<svg.*?</svg>", " ", cell, flags=re.S))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", "", text)
    tiles = [norm_tile(t) for t in TILE_RE.findall(cell)]
    verb = text or "?"
    # normalise a few compound renderings
    for k in ("摸切", "明杠", "暗杠", "加杠", "自摸", "荣和", "跳过", "立直", "和了"):
        if k in text:
            verb = k
            break
    typ = VERB_MAP.get(verb, verb)
    if typ == "dahai":
        key = f"dahai:{tiles[0]}" if tiles else "dahai:?"
    elif typ == "none":
        key = "none"
    elif typ == "hora":
        key = "hora"
    else:
        key = f"{typ}:{'+'.join(sorted(tiles))}" if tiles else typ
    return verb, key, tiles


def parse_akino(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    body = raw.split("</style>", 1)[1]
    sections = re.split(r"<section[^>]*>", body)[1:]
    kyokus = []
    for sec in sections:
        entries = []
        for chunk in ENTRY_RE.findall(sec):
            m = JUNME_RE.search(chunk)
            junme, tiles_left = (int(m.group(1)), int(m.group(2))) if m else (None, None)
            ms = SHANTEN_RE.search(chunk)
            shanten = int(ms.group(1)) if ms else None
            ml = LOSS_RE.search(chunk)
            rank, n_cand = (int(ml.group(1)), int(ml.group(2))) if ml else (1, None)

            def span(role: str, end: str) -> str:
                marker = f'<span class="role">{role}: </span>'
                i = chunk.find(marker)
                if i < 0:
                    return ""
                i += len(marker)          # skip the "玩家: " / "Coach: " label itself
                j = chunk.find(end, i)
                return chunk[i:j if j > 0 else len(chunk)]

            # the player's action is followed by <br>; the Coach's action is
            # followed by the <details> block that holds the candidate table.
            p_verb, p_key, p_tiles = parse_action(span("玩家", "<br>"))
            c_verb, c_key, c_tiles = parse_action(span("Coach", "<details>"))

            cands = []
            for cell, i_, frac in ROW_RE.findall(chunk):
                _, key, tiles = parse_action(cell)
                cands.append({"key": key, "tiles": tiles, "pi": int(i_) + int(frac) / 1e5})
            entries.append({
                "junme": junme, "tiles_left": tiles_left, "shanten": shanten,
                "rank": rank, "rank_denom": n_cand,
                "player_key": p_key, "player_verb": p_verb, "player_tiles": p_tiles,
                "coach_key": c_key, "coach_verb": c_verb, "coach_tiles": c_tiles,
                "cands": cands,
            })
        kyokus.append(entries)
    return kyokus


# --------------------------------------------------------------------------- #
# 2. load one of our checkpoints' json report
# --------------------------------------------------------------------------- #
def action_key(a: dict) -> str:
    """mjai action dict -> comparison key (same convention as the report parser)."""
    t = a.get("type", "none")
    if t == "dahai":
        return "dahai:" + str(a.get("pai"))
    if t in ("chi", "pon", "kan"):
        return t            # calls compared by type only (see cmp_key)
    return t


def load_ours(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    ours, meta = [], data["review"]
    for k in meta["kyokus"]:
        rows = []
        for e in k["entries"]:
            exp = e["expected"]
            key = action_key(exp)
            akey = action_key(e["actual"])
            details = {action_key(d["action"]): d for d in e.get("details", [])}
            top = max(e["details"], key=lambda d: d["prob"]) if e["details"] else None
            rows.append({
                "key": key, "actual_key": akey, "is_equal": bool(e["is_equal"]),
                "junme": e["junme"], "tiles_left": e["tiles_left"], "shanten": e["shanten"],
                "prob": (top or {}).get("prob"), "tile": e.get("tile"),
                "tehai": e["state"].get("tehai"), "details": details,
                "actual": e["actual"], "expected": e["expected"],
            })
        ours.append(rows)
    return ours, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", type=Path, help="also write a Markdown report here")
    args = ap.parse_args()

    htm = next(TESTSET.glob(f"{TAG}_*.htm"))
    ak = parse_akino(htm)
    ak_flat = [e for k in ak for e in k]
    print(f"parsed Akino Hana report : {htm.name}")
    print(f"  decisions              : {len(ak_flat)}   kyokus: {[len(k) for k in ak]}")
    ak_agree = sum(1 for e in ak_flat if e["rank"] == 1)
    print(f"  Akino Hana vs human    : {ak_agree}/{len(ak_flat)} = "
          f"{100.0 * ak_agree / len(ak_flat):.1f}%   (filename says 77.3% / 167-216)")
    print(f"  candidate counts       : {collections.Counter(len(e['cands']) for e in ak_flat)}")
    print(f"  Coach action types     : "
          f"{collections.Counter(e['coach_key'].split(':')[0] for e in ak_flat)}")
    print(f"  player action types    : "
          f"{collections.Counter(e['player_key'].split(':')[0] for e in ak_flat)}")
    print()

    models = [
        ("best.pth (20k, review default)", JSON_DIR / f"{TAG}_best20k.json"),
        ("2024v4best (base)", JSON_DIR / f"{TAG}_2024v4best.json"),
        ("finetune 107,091", JSON_DIR / f"{TAG}_finetune_step107091_agree85.17.json"),
        ("finetune 214,183", JSON_DIR / f"{TAG}_finetune_step214183_agree88.57.json"),
        ("finetune 321,275 (adopted)", JSON_DIR / f"{TAG}_finetune_step321275.json"),
        ("finetune 428,367", JSON_DIR / f"{TAG}_finetune_step428367.json"),
    ]

    header = (f"{'model':28} {'vs human':>12} {'vs AkinoHana':>13} "
              f"{'both':>5} {'onlyAK':>6} {'onlyUS':>6} {'neither':>7}")
    print(header)
    print("-" * len(header))

    results = {}
    for name, path in models:
        if not path.is_file():
            print(f"{name:28} (missing {path.name})")
            continue
        ours, meta = load_ours(path)
        # sanity: same decision count per kyoku
        assert [len(k) for k in ours] == [len(k) for k in ak], "kyoku shape mismatch"
        o_flat = [e for k in ours for e in k]

        # offsets while walking, so we can check alignment
        mis = 0
        for a, o in zip(ak_flat, o_flat):
            if (a["junme"], a["tiles_left"]) != (o["junme"], o["tiles_left"]):
                mis += 1
        vs_human = sum(1 for o in o_flat if o["is_equal"])
        same_model = sum(1 for a, o in zip(ak_flat, o_flat)
                         if cmp_key(a["coach_key"]) == cmp_key(o["key"]))
        # soft fit: how much probability OUR model puts on Akino Hana's top-1
        soft = []
        for a, o in zip(ak_flat, o_flat):
            d = o["details"].get(cmp_key(a["coach_key"]))
            if d is not None:
                soft.append(d["prob"])
        soft_mean = sum(soft) / len(soft) if soft else float("nan")
        both = sum(1 for a, o in zip(ak_flat, o_flat)
                   if a["rank"] == 1 and o["is_equal"])
        only_ak = sum(1 for a, o in zip(ak_flat, o_flat)
                      if a["rank"] == 1 and not o["is_equal"])
        only_us = sum(1 for a, o in zip(ak_flat, o_flat)
                      if a["rank"] != 1 and o["is_equal"])
        neither = sum(1 for a, o in zip(ak_flat, o_flat)
                      if a["rank"] != 1 and not o["is_equal"])
        n = len(ak_flat)
        print(f"{name:28} {vs_human:>5}/{n} {same_model:>6}/{n} "
              f"{both:>5} {only_ak:>6} {only_us:>6} {neither:>7}"
              f"   P(ours on AK top1)={soft_mean:.3f}"
              + (f"   [align warnings: {mis}]" if mis else ""))
        results[name] = {
            "vs_human": vs_human, "same_model": same_model, "n": n,
            "both": both, "only_ak": only_ak, "only_us": only_us,
            "neither": neither, "ak": ak_flat, "ours": o_flat,
            "soft_mean": soft_mean, "n_soft": len(soft),
        }

    # ------------------------------------------------------------------ #
    # detail for the adopted model
    # ------------------------------------------------------------------ #
    adopted = "finetune 321,275 (adopted)"
    if adopted not in results:
        return 0
    r = results[adopted]
    ak_flat, o_flat = r["ak"], r["ours"]
    diffs = [(i, a, o) for i, (a, o) in enumerate(zip(ak_flat, o_flat))
             if cmp_key(a["coach_key"]) != cmp_key(o["key"])]

    print(f"\n=== where our model differs from Akino Hana: {len(diffs)}/{r['n']} decisions ===")
    conf_agree, conf_dis = [], []
    for i, a, o in zip(range(len(ak_flat)), ak_flat, o_flat):
        if cmp_key(a["coach_key"]) == cmp_key(o["key"]):
            conf_agree.append(a["cands"][0]["pi"] if a["cands"] else 0.0)
        else:
            conf_dis.append(a["cands"][0]["pi"] if a["cands"] else 0.0)
    if conf_agree and conf_dis:
        print(f"Akino Hana top-1 pi when we AGREE  : mean {sum(conf_agree)/len(conf_agree):5.1f}"
              f"  median {sorted(conf_agree)[len(conf_agree)//2]:5.1f}  (n={len(conf_agree)})")
        print(f"Akino Hana top-1 pi when we DIFFER : mean {sum(conf_dis)/len(conf_dis):5.1f}"
              f"  median {sorted(conf_dis)[len(conf_dis)//2]:5.1f}  (n={len(conf_dis)})")

    lines = []
    lines.append(f"# test03 decision-level comparison\n")
    lines.append(f"- game: `{htm.name}`")
    lines.append(f"- Akino Hana vs human: **{ak_agree}/{len(ak_flat)} = "
                 f"{100.0*ak_agree/len(ak_flat):.2f}%**")
    lines.append("")
    lines.append("| model | vs human | vs Akino Hana (top-1) | P(ours on AK top-1) | both agree | only AkinoHana | only ours | neither |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, _ in models:
        if name not in results:
            continue
        v = results[name]
        lines.append(f"| {name} | {v['vs_human']}/{v['n']} = {100.0*v['vs_human']/v['n']:.2f}% "
                     f"| {v['same_model']}/{v['n']} = {100.0*v['same_model']/v['n']:.2f}% "
                     f"| {v['soft_mean']:.3f} "
                     f"| {v['both']} | {v['only_ak']} | {v['only_us']} | {v['neither']} |")
    lines.append("")
    lines.append(f"## Decisions where the adopted model differs from Akino Hana ({len(diffs)})\n")
    lines.append("| # | kyoku/junme | shanten | hand | Akino Hana | our model | human | human rank | AK top1 pi |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for i, a, o in diffs:
        hand = " ".join(o["tehai"] or [])
        lines.append(
            f"| {i+1} | J{a['junme']} (left {a['tiles_left']}) | {a['shanten']} | {hand} "
            f"| {a['coach_key']} | {o['key']} | {o['actual_key']} "
            f"| {'#%d/%s' % (a['rank'], a['rank_denom']) if a['rank'] != 1 else 'match'} "
            f"| {a['cands'][0]['pi']:.2f} |")
    lines.append("")

    # ------------------------------------------------------------------ #
    # where do the disagreements sit in Akino Hana's confidence range?
    # ------------------------------------------------------------------ #
    buckets = [(0, 40), (40, 60), (60, 80), (80, 101)]
    agree_b = collections.Counter()
    diff_b = collections.Counter()
    for a, o in zip(ak_flat, o_flat):
        pi = a["cands"][0]["pi"] if a["cands"] else 0.0
        b = next(lbl for lo, hi in buckets
                 for lbl in [f"{lo}-{hi if hi <= 100 else '100'}"]
                 if lo <= pi < hi)
        (agree_b if cmp_key(a["coach_key"]) == cmp_key(o["key"]) else diff_b)[b] += 1
    print("\nAkino Hana top-1 confidence vs agreement with our model:")
    print(f"{'pi band':>10} {'agree':>7} {'differ':>7} {'diff rate':>10}")
    for lo, hi in buckets:
        b = f"{lo}-{hi if hi <= 100 else '100'}"
        tot = agree_b[b] + diff_b[b]
        rate = f"{100.0*diff_b[b]/tot:.1f}%" if tot else "-"
        print(f"{b:>10} {agree_b[b]:>7} {diff_b[b]:>7} {rate:>10}")

    if args.markdown:
        lines.append("## Where the disagreements sit\n")
        lines.append("| Akino Hana top-1 π | we agree | we differ | differ rate |")
        lines.append("|---|---|---|---|")
        for lo, hi in buckets:
            b = f"{lo}-{hi if hi <= 100 else '100'}"
            tot = agree_b[b] + diff_b[b]
            rate = f"{100.0*diff_b[b]/tot:.1f}%" if tot else "-"
            lines.append(f"| {b} | {agree_b[b]} | {diff_b[b]} | {rate} |")
        lines.append("")
        lines.append("## Reading\n")
        lines.append(f"- Akino Hana agrees with the human on **167/216 = 77.31%** of decisions (the number "
                     f"encoded in the test-set filename).")
        ad = results[adopted]
        lines.append(f"- The adopted model agrees with the human on "
                     f"**{ad['vs_human']}/{ad['n']} = {100.0*ad['vs_human']/ad['n']:.2f}%** -> deviation "
                     f"**{(100.0*ad['vs_human']/ad['n']) - 77.31:+.2f} pts**.")
        lines.append(f"- It matches Akino Hana's own top-1 choice on {ad['same_model']}/{ad['n']} = "
                     f"{100.0*ad['same_model']/ad['n']:.1f}% of decisions and puts "
                     f"{ad['soft_mean']*100:.1f}% average probability mass on Akino Hana's choice.")
        lines.append("- The two models agree with the human on the *same* decisions only "
                     f"{ad['both']} times; {ad['only_ak']} decisions are matched by Akino Hana alone and "
                     f"{ad['only_us']} by the finetuned model alone -- the residual error is symmetric.")
        lines.append("")
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nmarkdown written -> {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
