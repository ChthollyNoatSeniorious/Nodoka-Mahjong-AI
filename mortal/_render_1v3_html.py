#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render 1v3 battle mjai logs as review-style HTML pages.

Every decision in a 1v3 log carries engine meta (q_values/mask_bits/shanten),
so each page shows, for every engine decision of every player:
  * the hand before the move, the tile actually played, the engine's #1 pick
  * the full candidate list with probability bars (softmax over q_values)
  * whether the actual move matched the engine's own top pick
  * per-kyoku and per-game agreement rate + confidence-bucket distribution

Output: <out_dir>/<game>.html plus <out_dir>/index.html (overview table).

Usage:
    python _render_1v3_html.py [--in DIR] [--out DIR] [--challenger NAME]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import html as _html
import json
import math
import os
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- action / tile tables (libriichi v4) --------------------------------
MJAI_TILES = ["1m","2m","3m","4m","5m","6m","7m","8m","9m",
              "1p","2p","3p","4p","5p","6p","7p","8p","9p",
              "1s","2s","3s","4s","5s","6s","7s","8s","9s",
              "E","S","W","N","P","F","C",
              "5mr","5pr","5sr"]
TILE_ID = {t: i for i, t in enumerate(MJAI_TILES)}

ACTION_LABEL = {
    37: "立直", 41: "碰", 42: "杠", 43: "和了", 44: "流局", 45: "過",
}
HONOR = {"E": "東", "S": "南", "W": "西", "N": "北", "P": "白", "F": "發", "C": "中"}
SUIT_ZH = {"m": "萬", "p": "筒", "s": "索"}
WINDS = ("東", "南", "西", "北")
BUCKETS = [(40, "#9a6700"), (60, "#cf222e"), (80, "#1f6feb"), (101, "#1a7f37")]


def esc(s):
    return _html.escape(str(s), quote=True)


def tile_span(t: str, red=False) -> str:
    """'4m'|'5sr'|'C' -> styled tile chip."""
    t = t.upper()
    if t in HONOR:
        txt = HONOR[t]
    else:
        is_r = t.endswith("R")
        base = t[:-1] if is_r else t
        if len(base) == 2 and base[0].isdigit() and base[1] in SUIT_ZH:
            txt = f"{base[0]}{SUIT_ZH[base[1]]}"
        else:
            txt = t
        red = red or is_r
    cls = "tile red" if red else "tile"
    return f'<span class="{cls}">{esc(txt)}</span>'


def tile_id(s: str) -> int:
    if s in TILE_ID:
        return TILE_ID[s]
    return TILE_ID[s.upper()]


def action_name(idx: int, pai: str = "", consumed=None) -> str:
    if idx <= 36:
        return f"打 {MJAI_TILES[idx]}" if pai else "打"
    if idx in ACTION_LABEL:
        pre = ACTION_LABEL[idx]
        if idx in (41, 42) and pai:
            pre = f"{pre} {pai}"
        return pre
    return f"#{idx}"


def chi_idx(consumed, pai) -> int:
    ids = sorted(tile_id(t) % 9 for t in consumed)  # position within suit
    tp = tile_id(pai) % 9
    if tp < ids[0]:
        return 38       # low
    if tp < ids[1]:
        return 39       # mid
    return 40           # high


def actual_action_index(ev: dict) -> int:
    t = ev["type"]
    pai = ev.get("pai")
    consumed = ev.get("consumed") or []
    if t == "dahai":
        return tile_id(pai)
    if t == "reach":
        return 37
    if t == "chi":
        return chi_idx(consumed, pai)
    if t == "pon":
        return 41
    if t in ("daiminkan", "ankan", "kakan"):
        return 42
    if t in ("hora", "tsumo_agari", "ron"):
        return 43
    if t == "ryukyoku":
        return 44
    return -1


def softmax(vals):
    m = max(vals)
    ex = [math.exp(x - m) for x in vals]
    s = sum(ex)
    return [x / s for x in ex]


def bucket_color(pi: float) -> str:
    for lim, color in BUCKETS:
        if pi < lim:
            return color
    return BUCKETS[-1][1]


def bucket_label(pi: float) -> str:
    if pi < 40:
        return "低置信"
    if pi < 60:
        return "中低"
    if pi < 80:
        return "中高"
    return "高置信"


# ---- replay --------------------------------------------------------------
class PlayerState:
    __slots__ = ("seat", "hand", "fuuro", "kawa", "riichi", "riichi_ok", "junme")

    def __init__(self, seat):
        self.seat = seat
        self.hand = []          # list of mjai tile strings
        self.fuuro = []         # list of dicts {type, tiles}
        self.kawa = []          # list of (pai, tsumogiri)
        self.riichi = False
        self.riichi_ok = False
        self.junme = 0

    def hand_copy(self):
        return list(self.hand)


class Decision:
    __slots__ = ("seat", "ev", "hand", "fuuro", "meta", "cands", "probs", "actual_idx",
                 "top_idx", "is_equal", "junme", "kyoku", "honba", "wind")

    def __init__(self, seat, ev, hand, fuuro, meta, junme, kyoku, honba, wind):
        self.seat = seat
        self.ev = ev
        self.hand = hand
        self.fuuro = fuuro
        self.meta = meta or {}
        self.junme = junme
        self.kyoku = kyoku
        self.honba = honba
        self.wind = wind
        q = meta.get("q_values") or []
        # engine stores None for masked/invalid actions; give them bottom probability
        q = [v if isinstance(v, (int, float)) else -1e9 for v in q]
        mb = int(meta.get("mask_bits", 0))
        bits = [i for i in range(46) if (mb >> i) & 1]
        if len(bits) != len(q):
            # fall back to first len(q) set bits semantics; flag length mismatch
            bits = bits[:len(q)]
        self.cands = bits
        self.probs = softmax(q) if len(q) == len(bits) and q else [0.0] * len(bits)
        self.actual_idx = actual_action_index(ev)
        top = max(range(len(self.probs)), key=lambda i: self.probs[i]) if self.probs else -1
        self.top_idx = self.cands[top] if top >= 0 else -1
        self.is_equal = (self.actual_idx == self.top_idx)

    @property
    def act_pai(self):
        return self.ev.get("pai") or ""

    @property
    def act_consumed(self):
        return self.ev.get("consumed") or []

    @property
    def top_pai(self):
        return ""

    @property
    def top_prob(self):
        return max(self.probs) * 100 if self.probs else 0.0


def replay_game(path: str):
    """Return (names, scores, kyokus) where kyokus is a list of kyoku dicts
    with per-player decision lists."""
    names = None
    scores = [25000] * 4
    ps = [PlayerState(i) for i in range(4)]
    kyokus = []
    cur = None          # current kyoku dict
    riichi_pending = [False] * 4   # reach declared, next dahai is riichi discard
    events_decisions = 0
    total_meta = 0

    def fresh_kyoku(ev):
        return {
            "kyoku": ev.get("kyoku", 1),
            "honba": ev.get("honba", 0),
            "bakaze": ev.get("bakaze", "E"),
            "oya": ev.get("oya", 0),
            "dora": ev.get("dora_marker", ""),
            "scores0": list(ev.get("scores") or [25000] * 4),
            "end": None,
            "decisions": [[] for _ in range(4)],
            "n_meta": 0,
        }

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            t = ev["type"]
            if t == "start_game":
                names = ev.get("names") or []
                continue
            if t == "start_kyoku":
                cur = fresh_kyoku(ev)
                kyokus.append(cur)
                scores = list(ev.get("scores") or scores)
                for p in ps:
                    p.hand = list(ev["tehais"][p.seat])
                    p.fuuro = []
                    p.kawa = []
                    p.riichi = False
                    p.riichi_ok = False
                    p.junme = 0
                riichi_pending = [False] * 4
                continue
            if t == "end_kyoku":
                if cur is not None:
                    cur["end"] = ev
                continue
            if t == "end_game":
                break
            if t == "tsumo":
                ps[ev["actor"]].hand.append(ev["pai"])
                ps[ev["actor"]].junme += 1
                continue
            if t == "dahai":
                a = ev["actor"]
                hand = ps[a].hand_copy()
                meta = ev.get("meta")
                if meta:
                    cur["n_meta"] += 1
                    cur["decisions"][a].append(
                        Decision(a, ev, hand, [dict(f) for f in ps[a].fuuro], meta,
                                 ps[a].junme, cur["kyoku"], cur["honba"], ps[a].seat))
                pai = ev["pai"]
                if ev.get("tsumogiri") and ps[a].hand and ps[a].hand[-1] == pai:
                    ps[a].hand.pop()
                else:
                    try:
                        ps[a].hand.remove(pai)
                    except ValueError:
                        # tolerate replay drift (e.g. aka variance)
                        pass
                ps[a].kawa.append((pai, ev.get("tsumogiri", False)))
                if riichi_pending[a]:
                    ps[a].riichi_ok = True
                    riichi_pending[a] = False
                continue
            if t == "reach":
                a = ev["actor"]
                cur["decisions"][a].append(
                    Decision(a, ev, ps[a].hand_copy(), [dict(f) for f in ps[a].fuuro],
                             ev.get("meta"), ps[a].junme, cur["kyoku"],
                             cur["honba"], ps[a].seat))
                ps[a].riichi = True
                riichi_pending[a] = True
                continue
            if t == "reach_accepted":
                continue
            if t in ("chi", "pon"):
                a, tg = ev["actor"], ev["target"]
                cur["decisions"][a].append(
                    Decision(a, ev, ps[a].hand_copy(), [dict(f) for f in ps[a].fuuro],
                             ev.get("meta"), ps[a].junme, cur["kyoku"],
                             cur["honba"], ps[a].seat))
                consumed = list(ev.get("consumed") or [])
                for c in consumed:
                    try:
                        ps[a].hand.remove(c)
                    except ValueError:
                        pass
                # remove the called tile from target's kawa (last occurrence)
                pai = ev.get("pai")
                for i in range(len(ps[tg].kawa) - 1, -1, -1):
                    if ps[tg].kawa[i][0] == pai:
                        del ps[tg].kawa[i]
                        break
                ps[a].fuuro.append({"type": t, "tiles": consumed + [pai]})
                continue
            if t in ("daiminkan", "ankan", "kakan"):
                a = ev["actor"]
                cur["decisions"][a].append(
                    Decision(a, ev, ps[a].hand_copy(), [dict(f) for f in ps[a].fuuro],
                             ev.get("meta"), ps[a].junme, cur["kyoku"],
                             cur["honba"], ps[a].seat))
                pai = ev.get("pai")
                consumed = list(ev.get("consumed") or [])
                if t == "daiminkan":
                    # remove the two hand copies; the third came from the target's kawa
                    for _ in range(2):
                        try:
                            ps[a].hand.remove(pai)
                        except ValueError:
                            pass
                    tg = ev.get("target")
                    for i in range(len(ps[tg].kawa) - 1, -1, -1):
                        if ps[tg].kawa[i][0] == pai:
                            del ps[tg].kawa[i]
                            break
                    # replace existing pon fuuro if present
                    for fr in ps[a].fuuro:
                        if fr["type"] == "pon" and fr["tiles"][-1] == pai:
                            fr["tiles"] = [pai] * 4
                            fr["type"] = "daiminkan"
                            break
                    else:
                        ps[a].fuuro.append({"type": "daiminkan", "tiles": [pai] * 4})
                elif t == "ankan":
                    tiles = list(consumed) if consumed else [pai] * 4
                    for c in tiles:
                        try:
                            ps[a].hand.remove(c)
                        except ValueError:
                            pass
                    ps[a].fuuro.append({"type": "ankan", "tiles": tiles})
                else:  # kakan
                    try:
                        ps[a].hand.remove(pai)
                    except ValueError:
                        pass
                    for fr in ps[a].fuuro:
                        if fr["type"] in ("pon", "daiminkan") and fr["tiles"][-1] == pai:
                            fr["tiles"] = [pai] * 4
                            fr["type"] = "kakan"
                            break
                    else:
                        ps[a].fuuro.append({"type": "kakan", "tiles": [pai] * 4})
                continue
            if t == "hora":
                cur["end"] = {"type": "hora", "actor": ev.get("actor"),
                              "target": ev.get("target"),
                              "deltas": ev.get("deltas")}
                scores = [s + d for s, d in zip(scores, ev.get("deltas") or [0] * 4)]
                continue
            if t == "ryukyoku":
                cur["end"] = {"type": "ryukyoku", "deltas": ev.get("deltas")}
                scores = [s + d for s, d in zip(scores, ev.get("deltas") or [0] * 4)]
                continue
            # dora / kyoutaku: no state needed
    return names, scores, kyokus


# ---- rendering -----------------------------------------------------------
def hand_html(hand, marked=()):
    return "".join(tile_span(t, red=(t in marked)) for t in hand)


def fuuro_html(fuuro):
    parts = []
    for fr in fuuro:
        tiles = "".join(tile_span(t) for t in fr["tiles"])
        parts.append(f'<span class="fuuro">{tiles}</span>')
    return "".join(parts)


def kawa_dots(fuuro_out):
    return f'<span class="fdot">副露{len(fuuro_out)}</span>' if fuuro_out else ""


def end_text(ends) -> str:
    if not ends:
        return ""
    e = ends
    if e.get("type") == "hora":
        a, tg = e.get("actor"), e.get("target")
        return "自摸" if a == tg else f"荣和(家{tg+1}→家{a+1})"
    if e.get("type") == "ryukyoku":
        return "流局"
    return ""


def decision_block(d: Decision, i: int) -> str:
    meta = d.meta or {}
    ev = d.ev
    t = ev["type"]
    act_pai = d.act_pai
    consumed = d.act_consumed
    pai = ev.get("pai")

    rows = []
    for j, idx in enumerate(d.cands):
        prob = d.probs[j] * 100
        chosen = (idx == d.actual_idx)
        is_top = (idx == d.top_idx)
        cls = "cand" + (" chosen" if chosen else "")
        tags = []
        if chosen:
            tags.append('<span class="tag tag-act">實際</span>')
        if is_top:
            tags.append('<span class="tag tag-top">引擎首選</span>')
        if chosen and d.is_equal:
            tags.append('<span class="tag tag-ok">一致✓</span>')
        elif chosen and not d.is_equal:
            tags.append('<span class="tag tag-no">分歧✗</span>')
        name = action_name(idx, pai, consumed)
        if idx in (38, 39, 40) and consumed and pai:
            name = "吃 " + "+".join(consumed) + f"+{pai}"
        if idx == 42:
            name = ("杠 " + " ".join(consumed)) if consumed else "杠"
            if t in ("ankan",) and not consumed and pai:
                name = f"杠 {pai}" if pai else "杠"
        w = max(0.5, prob)
        rows.append(
            f'<div class="{cls}">'
            f'<span class="cand-name">{esc(name)}</span>'
            f'<span class="cand-bar"><span class="cand-fill" style="width:{w:.1f}%"></span></span>'
            f'<span class="cand-p">{prob:.1f}%</span>'
            f'<span class="cand-tags">{"".join(tags)}</span>'
            f"</div>")

    status = ('<span class="ok">一致 ✓</span>' if d.is_equal
              else '<span class="no">分歧 ✗</span>')
    meta_extra = []
    if meta.get("is_greedy") is not None:
        meta_extra.append("貪婪" if meta["is_greedy"] else "採樣")
    if meta.get("at_furiten"):
        meta_extra.append("振聽")
    shanten = meta.get("shanten")
    sh = f"{shanten}向聽" if shanten is not None else ""
    ptxt = ""
    if t in ("dahai", "reach"):
        ptxt = f"巡{d.junme}"
    elif t in ("chi", "pon", "daiminkan"):
        ptxt = f"反應(巡{d.junme})"
    else:
        ptxt = f"巡{d.junme}"
    extra = (" · ".join(meta_extra)) if meta_extra else ""

    return f"""
    <div class="entry">
      <div class="entry-head">
        <span class="e-no">#{i}</span>
        <span class="e-meta">{ptxt} · {sh}{(" · " + esc(extra)) if extra else ""}</span>
        <span class="e-grade" style="background:{bucket_color(d.top_prob)}">
          {esc(bucket_label(d.top_prob))} {d.top_prob:.0f}%</span>
      </div>
      <div class="entry-body">
        <div class="handrow">
          <div class="hand">{hand_html(d.hand, marked=(consumed or [act_pai]))}
            {fuuro_html(d.fuuro)}</div>
        </div>
        <div class="act-row">
          <span class="act-actual">實際: {esc(action_text_ev(ev))}</span>
          <span class="act-expected">引擎首選: {esc(action_name(d.top_idx, pai, consumed))}</span>
          <span class="act-status">{status}</span>
        </div>
        <div class="cands">{"".join(rows)}</div>
      </div>
    </div>"""


def action_text_ev(ev) -> str:
    t = ev["type"]
    pai = ev.get("pai", "")
    consumed = ev.get("consumed") or []
    pre = {"dahai": "打", "reach": "立直", "chi": "吃", "pon": "碰",
           "daiminkan": "杠", "ankan": "杠", "kakan": "杠"}.get(t, t)
    if pai and t != "react":
        return f"{pre} {pai}"
    if consumed:
        return f"{pre} {'+'.join(consumed)}"
    return pre


def kyoku_block(k: dict, seat: int, i: int) -> str:
    decs = k["decisions"][seat]
    if not decs:
        return ""
    n = len(decs)
    n_eq = sum(1 for d in decs if d.is_equal)
    rate = 100.0 * n_eq / n if n else 0.0
    blocks = "".join(decision_block(d, j + 1) for j, d in enumerate(decs))
    wind = f"{WINDS[(k['kyoku'] - 1) % 4]}{(k['kyoku'] - 1) // 4 + 1}局"
    return f"""
    <div class="kyoku">
      <div class="kyoku-head">
        <span class="kyoku-name">{wind}</span>
        <span class="kyoku-honba">{k['honba']} 本場</span>
        <span class="kyoku-end">{esc(end_text(k['end']))}</span>
        <span class="kyoku-rate">一致率 {rate:.0f}% ({n_eq}/{n})</span>
      </div>
      {blocks}
    </div>"""


def player_section(names, scores, kyokus, seat) -> str:
    name = names[seat] if seat < len(names) else f"家{seat + 1}"
    decs = [d for k in kyokus for d in k["decisions"][seat]]
    n = len(decs)
    n_eq = sum(1 for d in decs if d.is_equal)
    rate = 100.0 * n_eq / n if n else 0.0
    kawas = []
    for k in kyokus:
        kawas.append(f'<span class="kawa">{k["kyoku"]}</span>')
    buckets = collections.Counter(bucket_label(d.top_prob) for d in decs)
    legend = "".join(
        f'<span class="gl" style="color:{bucket_color(
            {"低置信": 20, "中低": 50, "中高": 70, "高置信": 90}[b])}">{b} {c}</span>'
        for b, c in buckets.most_common())
    kyoku_html = "".join(kyoku_block(k, seat, i) for i, k in enumerate(kyokus))
    avg_pi = sum(d.top_prob for d in decs) / n if n else 0.0
    return f"""
    <div class="card">
      <div class="p-head">
        <span class="p-name">{esc(name)}</span>
        <span class="p-score">得分 {scores[seat]}</span>
        <span class="p-rate">一致率 <b>{rate:.1f}%</b> ({n_eq}/{n})</span>
        <span class="p-pi">首選均置信 {avg_pi:.1f}%</span>
      </div>
      <div style="margin:6px 0">{legend}</div>
      {kyoku_html}
    </div>"""


def render_game(path: str, chal_name: str) -> tuple[str, dict]:
    names, scores, kyokus = replay_game(path)
    gid = os.path.basename(path)[:-len(".json.gz")]
    order = sorted(range(4), key=lambda i: -scores[i])
    ranks = {seat: order.index(seat) + 1 for seat in range(4)}

    # per-player decision sections
    sect = []
    overview_rows = []
    for seat in range(4):
        name = names[seat] if seat < len(names) else f"家{seat + 1}"
        decs = [d for k in kyokus for d in k["decisions"][seat]]
        n = len(decs)
        n_eq = sum(1 for d in decs if d.is_equal)
        rate = 100.0 * n_eq / n if n else 0.0
        avg_pi = sum(d.top_prob for d in decs) / n if n else 0.0
        is_chal = (name == chal_name)
        overview_rows.append(
            f'<tr class="{"chal" if is_chal else ""}">'
            f'<td>{esc(name)}{" ★" if is_chal else ""}</td>'
            f'<td>{ranks[seat]}</td><td>{scores[seat]}</td>'
            f'<td>{rate:.1f}% ({n_eq}/{n})</td><td>{avg_pi:.1f}%</td></tr>')
        sect.append(player_section(names, scores, kyokus, seat))

    chal_idx = next((i for i, n in enumerate(names) if n == chal_name), None)
    chal_rank = ranks[chal_idx] if chal_idx is not None else "?"

    page = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>1v3 對戰檢討 {gid}</title>
<style>
 body{{font-family:"Segoe UI","Microsoft JhengHei",sans-serif;background:#f4f6fa;color:#1c2733;margin:0;padding:16px}}
 .wrap{{max-width:980px;margin:0 auto}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#667;font-size:13px;margin-bottom:12px}}
 .card{{background:#fff;border:1px solid #dfe3ea;border-radius:10px;padding:14px 18px;margin-bottom:14px}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 td,th{{border:1px solid #dfe3ea;padding:4px 8px;text-align:center}}
 tr.chal td{{background:#fff8e6;font-weight:600}}
 .p-head{{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}}
 .p-name{{font-size:16px;font-weight:700}}
 .p-rate b{{color:#1a7f37}}
 .p-pi{{color:#667;font-size:13px}}
 .gl{{margin-right:12px;font-size:12px}}
 .kyoku{{background:#fff;border:1px solid #dfe3ea;border-radius:10px;margin-bottom:12px;overflow:hidden}}
 .kyoku-head{{background:#eef2f8;padding:8px 14px;font-size:13px;display:flex;gap:12px;align-items:center}}
 .kyoku-name{{font-weight:700}}
 .kyoku-rate{{margin-left:auto;color:#1a7f37;font-weight:600}}
 .entry{{padding:10px 14px;border-top:1px dashed #e2e6ee}}
 .entry-head{{font-size:12px;color:#667;margin-bottom:6px;display:flex;gap:10px;align-items:center}}
 .e-grade{{color:#fff;border-radius:4px;padding:1px 7px;font-size:11px}}
 .handrow{{display:flex;gap:8px;align-items:center}}
 .hand{{margin-bottom:6px}}
 .fuuro{{display:inline-block;margin-left:6px}}
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
 .cand-name{{min-width:64px;text-align:right}}
 .cand-bar{{flex:1;background:#eef1f6;border-radius:4px;height:14px;overflow:hidden}}
 .cand-fill{{display:block;height:100%;background:#4c8bf5;border-radius:4px}}
 .cand.chosen .cand-fill{{background:#1a7f37}}
 .cand.chosen .cand-name{{font-weight:700}}
 .cand-p{{min-width:52px;text-align:right;color:#445}}
 .cand-tags{{min-width:110px}}
 .tag{{display:inline-block;font-size:10px;border-radius:3px;padding:1px 5px;margin-right:4px}}
 .tag-act{{background:#1a7f37;color:#fff}}
 .tag-top{{background:#4c8bf5;color:#fff}}
 .tag-ok{{background:#dcffe4;color:#1a7f37;border:1px solid #9fe3b0}}
 .tag-no{{background:#ffe0e0;color:#cf222e;border:1px solid #f0b0b0}}
 nav a{{margin-right:10px;font-size:13px}}
</style></head><body><div class="wrap">
 <div class="card">
  <h1>1v3 對戰檢討 · {esc(gid)}</h1>
  <div class="sub">挑戰者 <b>{esc(chal_name)}</b>(排名 {chal_rank}) vs 2024v4best ×3 ·
   對局數 {len(kyokus)} 局 · 決策總數 {sum(len(k['decisions'][s]) for k in kyokus for s in range(4))}</div>
  <table><tr><th>玩家</th><th>排名</th><th>得分</th><th>一致率</th><th>首選均置信</th></tr>
   {''.join(overview_rows)}</table>
 </div>
 <div class="sub" style="margin:10px 0">
  <nav>{''.join(f'<a href="#p{seat}">{esc(names[seat])}</a>' for seat in range(4))}</nav>
 </div>
 {''.join(f'<div id="p{seat}">{s}</div>' for seat, s in enumerate(sect))}
</div></body></html>"""
    return page, {"gid": gid, "names": names, "scores": scores, "ranks": ranks,
                  "chal_idx": chal_idx, "n_kyoku": len(kyokus),
                  "n_dec": sum(len(k["decisions"][s]) for k in kyokus for s in range(4))}


def render_index(rows: list[dict], chal_name: str, out_dir: pathlib.Path):
    by_rank = collections.Counter()
    by_rank_chal = collections.Counter()
    chal_rows = [r for r in rows if r["chal_idx"] is not None]
    for r in rows:
        for seat in range(4):
            pass
    # per-game challenger info comes from rows
    lines = []
    for r in sorted(rows, key=lambda x: x["gid"]):
        by_rank_chal[r["ranks"][r["chal_idx"]]] += 1
        lines.append(
            f'<tr><td><a href="{r["gid"]}.html">{esc(r["gid"])}</a></td>'
            f'<td>{r["ranks"][r["chal_idx"]]}</td>'
            f'<td>{r["scores"][r["chal_idx"]]}</td>'
            f'<td>{esc(r["names"][0])} {r["scores"][0]}</td>'
            f'<td>{esc(r["names"][1])} {r["scores"][1]}</td>'
            f'<td>{esc(r["names"][2])} {r["scores"][2]}</td>'
            f'<td>{esc(r["names"][3])} {r["scores"][3]}</td></tr>')
    n = sum(by_rank_chal.values())
    rank_str = " / ".join(f"{k}位×{by_rank_chal[k]}" for k in range(1, 5))
    avg_rank = sum(k * by_rank_chal[k] for k in range(1, 5)) / n if n else 0
    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>1v3 對戰彙總 ({n} 場)</title>
<style>
 body{{font-family:"Segoe UI","Microsoft JhengHei",sans-serif;background:#f4f6fa;color:#1c2733;margin:16px}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 td,th{{border:1px solid #dfe3ea;padding:3px 6px;text-align:center}}
 a{{color:#1f6feb}}
 h1{{font-size:20px}} .sub{{color:#667;font-size:13px;margin-bottom:10px}}
</style></head><body>
<h1>1v3 對戰彙總 · {esc(chal_name)} vs 2024v4best ×3</h1>
<div class="sub">共 {n} 場 · 挑戰者排名分布: {rank_str} · 平均名次 {avg_rank:.2f}</div>
<table><tr><th>對局</th><th>挑戰者排名</th><th>挑戰者得分</th><th>東家</th><th>南家</th><th>西家</th><th>北家</th></tr>
{''.join(lines)}</table>
</body></html>"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", type=pathlib.Path,
                    default=pathlib.Path("output/1v3_100"))
    ap.add_argument("--out", dest="out_dir", type=pathlib.Path,
                    default=pathlib.Path("output/1v3_100_html"))
    ap.add_argument("--challenger", default="mortal")
    args = ap.parse_args()

    files = sorted(p for p in args.in_dir.glob("*.gz"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, p in enumerate(files, 1):
        try:
            page, info = render_game(str(p), args.challenger)
        except Exception as exc:
            print(f"  [{i}/{len(files)}] SKIP {p.name}: {exc!r}", flush=True)
            continue
        (args.out_dir / f"{info['gid']}.html").write_text(page, encoding="utf-8")
        rows.append(info)
        if i % 20 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] ok={len(rows)}", flush=True)
    render_index(rows, args.challenger, args.out_dir)
    print(f"done: {len(rows)} html -> {args.out_dir} (index.html included)")
    return 0


if __name__ == "__main__":
    sys.exit(main())