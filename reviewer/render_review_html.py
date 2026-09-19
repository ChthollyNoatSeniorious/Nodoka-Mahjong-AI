#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render self-contained review HTML pages from fetched api_runs JSON.

Each page shows, for every decision of the reviewed player:
  * the hand, the tile actually played, the engine's #1 pick
  * the full candidate list with probability bars (what gokujan shows)
  * whether the actual move matched RIGEL 1.4's top pick (is_equal)
  * per-game and per-kyoku agreement rate + grade bucket distribution

Output: reviewer/out/html_export/<taskid>.html  (offline-viewable, no JS)

Usage:
    python reviewer/render_review_html.py --list reviewer/out/_txt_ids.txt
"""
from __future__ import annotations

import argparse
import collections
import html as _html
import json
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
API_RUNS = HERE / "out" / "api_runs"
OUT_DIR = HERE / "out" / "html_export"
STATE = HERE / "out" / "bigcoach_runs" / "_state.json"
ID_RE = re.compile(r"[0-9a-f]{16}")

ACTION_LABEL = {
    "dahai": "打", "tsumo": "自摸", "ron": "荣和",
    "pon": "碰", "chi": "吃", "ankan": "杠", "daiminkan": "杠",
    "kakan": "加杠", "riichi": "立直", "draw": "摸牌",
    "none": "—", "end": "—", "ryukyoku": "流局",
}
GRADE_COLOR = {
    "best": "#1a7f37", "good": "#1f6feb", "inaccuracy": "#9a6700",
    "mistake": "#cf222e", "blunder": "#82071e",
}
GRADE_ZH = {
    "best": "最佳", "good": "良好", "inaccuracy": "不準",
    "mistake": "失誤", "blunder": "大錯",
}

HONOR = {"E": "東", "S": "南", "W": "西", "N": "北", "P": "白", "F": "發", "C": "中"}
SUIT_ZH = {"m": "萬", "p": "筒", "s": "索"}


def esc(s):
    return _html.escape(str(s), quote=True)


def tile_span(t: str) -> str:
    """'4m'|'5sr'|'C'|'S' -> styled tile chip."""
    t = t.upper()
    if t in HONOR:
        return f'<span class="tile">{esc(HONOR[t])}</span>'
    red = t.endswith("R")
    if red:
        t = t[:-1]
    suit = t[-1].lower() if t and t[-1].isalpha() else ""
    num = "".join(ch for ch in t if ch.isdigit()) or "?"
    if suit in SUIT_ZH:
        txt = f"{num}{SUIT_ZH[suit]}"
    else:
        txt = t
    cls = "tile red" if red else "tile"
    return f'<span class="{cls}">{esc(txt)}</span>'


def action_text(a: dict) -> str:
    if not a:
        return ""
    t = a.get("type", "")
    pre = ACTION_LABEL.get(t, t)
    pai = a.get("pai")
    if pai:
        return f"{pre} {pai}"
    consumed = a.get("consumed")
    if consumed:
        return f"{pre} {'+'.join(consumed)}"
    return pre


def render_hands(hand: list[str]) -> str:
    return " ".join(tile_span(t) for t in hand)


def entry_block(e: dict, i: int) -> str:
    actual = e.get("actual") or {}
    expected = e.get("expected") or {}
    is_eq = bool(e.get("is_equal"))
    details = e.get("details") or []
    act_idx = e.get("actual_index")
    grade = e.get("grade_bucket") or ""
    gcolor = GRADE_COLOR.get(grade, "#888")
    gzh = GRADE_ZH.get(grade, grade)
    state = e.get("state") or {}
    hand = state.get("tehai") or []
    actual_pai = actual.get("pai") or ""
    exp_pai = expected.get("pai") or ""

    rows = []
    for j, det in enumerate(details):
        a = det.get("action") or {}
        prob = float(det.get("prob", 0.0)) * 100.0
        chosen = j == act_idx
        is_top = j == 0
        cls = "cand"
        tag = []
        if chosen:
            cls += " chosen"
            tag.append('<span class="tag tag-act">實際</span>')
        if is_top:
            tag.append('<span class="tag tag-top">引擎首選</span>')
        if chosen and is_eq:
            tag.append('<span class="tag tag-ok">一致✓</span>')
        elif chosen and not is_eq:
            tag.append('<span class="tag tag-no">分歧✗</span>')
        w = max(0.5, prob)
        rows.append(
            f'<div class="{cls}">'
            f'<span class="cand-name">{esc(action_text(a))}</span>'
            f'<span class="cand-bar"><span class="cand-fill" style="width:{w:.1f}%"></span></span>'
            f'<span class="cand-p">{prob:.1f}%</span>'
            f'<span class="cand-tags">{"".join(tag)}</span>'
            f"</div>")

    status = '<span class="ok">一致 ✓</span>' if is_eq else '<span class="no">分歧 ✗</span>'
    return f"""
    <div class="entry">
      <div class="entry-head">
        <span class="e-no">#{i}</span>
        <span class="e-meta">巡目 {e.get('junme','?')} · 餘牌 {e.get('tiles_left','?')} ·
          {esc(e.get('shanten','?')) if e.get('shanten') is not None else ''}向聽</span>
        <span class="e-grade" style="background:{gcolor}">{esc(gzh)}</span>
      </div>
      <div class="entry-body">
        <div class="hand">{render_hands(hand)}</div>
        <div class="act-row">
          <span class="act-actual">實際: {tile_span(actual_pai) if actual_pai else esc(action_text(actual))}</span>
          <span class="act-expected">引擎首選: {tile_span(exp_pai) if exp_pai else esc(action_text(expected))}</span>
          <span class="act-status">{status}</span>
        </div>
        <div class="cands">{"".join(rows)}</div>
      </div>
    </div>"""


WINDS = ("東", "南", "西", "北")


def wind_text(num: int) -> str:
    return f"{WINDS[num % 4]}{num // 4 + 1}局"


def end_text(ends) -> str:
    if not ends:
        return ""
    e = ends[0]
    t = e.get("type", "")
    actor = e.get("actor")
    target = e.get("target")
    if t == "hora":
        kind = "自摸" if actor == target else "荣和"
        return f"{kind}" + (f"(家{actor + 1}→家{target + 1})" if actor != target else f"(家{actor + 1})")
    if t == "ryukyoku":
        return "流局"
    return str(t)


def kyoku_block(k: dict) -> str:
    num = k.get("kyoku", 0)
    honba = k.get("honba", 0)
    end = end_text(k.get("end_status"))
    entries = k.get("entries") or []
    n_eq = sum(1 for e in entries if e.get("is_equal"))
    blocks = "".join(entry_block(e, i + 1) for i, e in enumerate(entries))
    rate = 100.0 * n_eq / len(entries) if entries else 0.0
    return f"""
    <div class="kyoku">
      <div class="kyoku-head">
        <span class="kyoku-name">{wind_text(num)}</span>
        <span class="kyoku-honba">{honba} 本場</span>
        <span class="kyoku-end">{esc(end)}</span>
        <span class="kyoku-rate">一致率 {rate:.0f}% ({n_eq}/{len(entries)})</span>
      </div>
      {blocks}
    </div>"""


def render_game(gid: str) -> str | None:
    src = API_RUNS / f"{gid}.json"
    if not src.exists():
        return None
    d = json.loads(src.read_text(encoding="utf-8"))
    rv = d.get("review") or {}
    kyokus = rv.get("kyokus") or []
    entries = [e for k in kyokus for e in (k.get("entries") or [])]
    n = len(entries)
    n_eq = sum(1 for e in entries if e.get("is_equal"))
    rate = 100.0 * n_eq / n if n else 0.0
    grades = collections.Counter(e.get("grade_bucket") or "?" for e in entries)

    grade_legend = "".join(
        f'<span class="gl" style="color:{GRADE_COLOR.get(g,"#888")}">'
        f'{GRADE_ZH.get(g,g)} {c}</span>' for g, c in grades.most_common())

    paipu = ""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        for r in st.get("results", []):
            if r.get("taskId") == gid and r.get("paipu"):
                paipu = r["paipu"]
                break
    except Exception:
        pass

    kyoku_html = "".join(kyoku_block(k) for k in kyokus)

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>RIGEL 1.4 复盘 {gid}</title>
<style>
 body{{font-family:"Segoe UI","Microsoft JhengHei",sans-serif;background:#f4f6fa;color:#1c2733;margin:0;padding:16px}}
 .wrap{{max-width:900px;margin:0 auto}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#667;font-size:13px;margin-bottom:12px}}
 .card{{background:#fff;border:1px solid #dfe3ea;border-radius:10px;padding:14px 18px;margin-bottom:14px}}
 .rate-big{{font-size:34px;font-weight:700;color:#1a7f37}}
 .rate-line{{font-size:13px;color:#667;margin-top:2px}}
 .gl{{margin-right:14px;font-size:13px}}
 .kyoku{{background:#fff;border:1px solid #dfe3ea;border-radius:10px;margin-bottom:14px;overflow:hidden}}
 .kyoku-head{{background:#eef2f8;padding:8px 14px;font-size:14px;display:flex;gap:14px;align-items:center}}
 .kyoku-name{{font-weight:700}}
 .kyoku-rate{{margin-left:auto;color:#1a7f37;font-weight:600}}
 .entry{{padding:10px 14px;border-top:1px dashed #e2e6ee}}
 .entry-head{{font-size:12px;color:#667;margin-bottom:6px;display:flex;gap:10px;align-items:center}}
 .e-grade{{color:#fff;border-radius:4px;padding:1px 7px;font-size:11px}}
 .entry-body{{}}
 .hand{{margin-bottom:8px}}
 .tile{{display:inline-block;min-width:30px;text-align:center;border:1px solid #c8cdd6;border-radius:5px;
   background:#fff;padding:3px 4px;margin:1px;font-size:13px;color:#223}}
 .tile.red{{background:#ffd9d9;border-color:#e5a3a3;color:#8b1a1a}}
 .act-row{{display:flex;gap:16px;align-items:center;font-size:14px;margin-bottom:8px}}
 .act-actual{{font-weight:700}}
 .act-expected{{color:#445}}
 .ok{{color:#1a7f37;font-weight:700}}
 .no{{color:#cf222e;font-weight:700}}
 .cands{{display:flex;flex-direction:column;gap:3px}}
 .cand{{display:flex;align-items:center;gap:8px;font-size:13px}}
 .cand-name{{min-width:70px;text-align:right}}
 .cand-bar{{flex:1;background:#eef1f6;border-radius:4px;height:14px;overflow:hidden}}
 .cand-fill{{display:block;height:100%;background:#4c8bf5;border-radius:4px}}
 .cand.chosen .cand-fill{{background:#1a7f37}}
 .cand.chosen .cand-name{{font-weight:700}}
 .cand-p{{min-width:52px;text-align:right;color:#445}}
 .cand-tags{{min-width:150px}}
 .tag{{display:inline-block;font-size:10px;border-radius:3px;padding:1px 5px;margin-right:4px}}
 .tag-act{{background:#1a7f37;color:#fff}}
 .tag-top{{background:#4c8bf5;color:#fff}}
 .tag-ok{{background:#dcffe4;color:#1a7f37;border:1px solid #9fe3b0}}
 .tag-no{{background:#ffe0e0;color:#cf222e;border:1px solid #f0b0b0}}
</style></head><body><div class="wrap">
 <div class="card">
  <h1>極雀 RIGEL 1.4 复盘 · 與長明 1.4 一致率</h1>
  <div class="sub">taskId: {gid}· 引擎: 長明 RIGEL 1.4 · 決策數: {n}{(" · paipu: " + esc(paipu)) if paipu else ""}</div>
  <div class="rate-big">{rate:.1f}%</div>
  <div class="rate-line">與長明 1.4 頂尖推薦一致 {n_eq}/{n} 手</div>
  <div style="margin-top:8px">{grade_legend}</div>
 </div>
 {kyoku_html}
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=pathlib.Path,
                    default=HERE / "out" / "_txt_ids.txt",
                    help="file with task ids (one per line)")
    ap.add_argument("--out", type=pathlib.Path, default=OUT_DIR)
    args = ap.parse_args()

    ids = []
    for line in args.list.read_text(encoding="utf-8").splitlines():
        m = ID_RE.search(line.strip())
        if m:
            ids.append(m.group(0))
    ids = list(dict.fromkeys(ids))
    args.out.mkdir(parents=True, exist_ok=True)

    n_ok = n_skip = 0
    for i, gid in enumerate(ids, 1):
        h = render_game(gid)
        if h is None:
            n_skip += 1
            continue
        (args.out / f"{gid}.html").write_text(h, encoding="utf-8")
        n_ok += 1
        if i % 50 == 0:
            print(f"  [{i}/{len(ids)}] ok={n_ok} skip={n_skip}", flush=True)
    print(f"done: rendered {n_ok} html -> {args.out} (skipped {n_skip})")
    return 0


if __name__ == "__main__":
    sys.exit(main())