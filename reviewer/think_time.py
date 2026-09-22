#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每打思考時間分析 + 數據可視化(MahjongSoul 牌譜)。

原理:mjsooul 官方牌譜 (v210715+) 的每條 GameAction 都帶 `passed`
= 對局內累計毫秒(回放時鐘)。本地 tensoul 服務新增了
`/api/v1/requests/:id/timeline` 端點,回傳未經 tenhou 轉換的原始時間軸:

    [{ts, type, input?, rec?, data?}, ...]

本工具把時間軸解析成「每一打」並計算思考時間:

    思考時間(think) = 當前動作 ts - 前一條記錄(rec)的 ts

* 打牌:前一條記錄是自己的 RecordDealTile(自動摸牌,+500ms 固定間隔)——
  所以「摸到打出」間隔就是純決策時間。
* 鳴牌(吃/碰/槓)/立直/和了:前一條記錄是觸發它的那張牌——間隔即響應窗口內
  的決策時間。
* 已知限制:
  - 「不鳴牌的 pass」沒有記錄(伺服器不存 pass),pass 決策時間無法單獨拆出;
  - 各動作間隔含少量網路/動畫延遲;首巡思考含起手整理;
  - 舊版牌譜(version < 210715)官方未存時間戳,timeline 為 null。

輸出至 <out>/thinktime_<id>/(默認 reviewer/out):
    report.html   自包含 SVG 圖表 + 表格(瀏覽器直接開)
    think_times.csv  每一打一行
    summary.json  統計匯總

用法:
    python reviewer\\think_time.py -u "<雀魂分享連結>"
    python reviewer\\think_time.py -u "<連結>" --no-open -o reviewer\\out
    python reviewer\\think_time.py path\\to\\saved_timeline.json
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

try:  # Windows console cp950-safe output
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import mjsoul_fetch

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"

PLAYER_COLORS = ["#e05252", "#3a9d5d", "#3a7bd5", "#e8a33d", "#8e6bc9"]

# records that are NOT a player's decision
AUTO_RECORDS = {
    "RecordNewRound",      # 開局(上下文,保留作前一事件)
    "RecordDealTile",      # 自動摸牌
    "RecordCollectedData",
    "RecordAnalysisedData",
}

# records where the round ends (kept as events, not moves)
EVENT_ONLY_RECORDS = {"RecordLiuJu"}

TYPE_LABELS = {
    "RecordDiscardTile": "打牌",
    "RecordChiPengGang": "鳴牌",
    "RecordAnGangAddGang": "槓",
    "RecordBaBei": "抜き(三麻)",
    "RecordChangeTile": "交換(三麻)",
    "RecordSelectGap": "選択(三麻)",
    "RecordHule": "和了",
    "RecordNoTile": "九種九牌",
    "RecordLiuJu": "流局",
    "RecordNewRound": "開局",
    "RecordDealTile": "摸牌",
}

CPG_LABELS = {0: "吃", 1: "碰", 2: "槓"}
ANKAN_LABELS = {2: "加槓", 3: "暗槓"}
WINDS = ["東", "南", "西", "北"]


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #

def parse_moves(names: list | None, timeline: list | None) -> tuple[list[dict], str | None]:
    """Return (moves, error). moves = list of dict rows."""
    if not timeline:
        return [], "該牌譜為舊版記錄(version < 210715),官方未存每打時間戳,無法分析思考時間"
    player_count = len(names) if names else 0

    moves: list[dict] = []
    prev_ts: int | None = None        # ts of previous RECORD entry
    prev_self_ts: dict[int, int] = {}  # ts of previous move by same seat
    kyoku = {"chang": 0, "ju": 0, "ben": 0}
    texts: list[str] = []

    def kyoku_label() -> str:
        wind = WINDS[(kyoku.get("chang", 0) or 0) % len(WINDS)]
        return f"{wind}{int(kyoku.get('ju', 0) or 0) + 1}局{int(kyoku.get('ben', 0) or 0)}本場"

    def add_move(seat: int, rec: str, ts: int, data: dict, note: str = "") -> None:
        nonlocal prev_self_ts
        think = ts - prev_ts if prev_ts is not None else None
        gap_self = ts - prev_self_ts[seat] if seat in prev_self_ts else None
        prev_self_ts[seat] = ts
        tile = data.get("tile") if isinstance(data, dict) else None
        moves.append({
            "idx": len(moves) + 1,
            "kyoku": kyoku_label(),
            "seat": seat,
            "player": names[seat] if names and seat < len(names) else f"座{seat + 1}",
            "type": TYPE_LABELS.get(rec, rec),
            "rec": rec,
            "tile": tile,
            "think_ms": think,
            "gap_self_ms": gap_self,
            "moqie": bool(data.get("moqie")) if isinstance(data, dict) else False,
            "liqi": bool(data.get("is_liqi")) if isinstance(data, dict) else False,
            "timeuse_s": None,
            "ts_ms": ts,
            "note": note,
        })

    for entry in timeline:
        ts = int(entry.get("ts") or 0)
        rec = entry.get("rec")
        data = entry.get("data") or {}
        input_ = entry.get("input") or {}

        if rec == "RecordNewRound":
            kyoku = {
                "chang": data.get("chang", kyoku["chang"]),
                "ju": data.get("ju", kyoku["ju"]),
                "ben": data.get("ben", 0),
            }
            prev_ts = ts
            continue
        if not rec:
            continue  # user_input twins / events without a broadcast record
        if rec in EVENT_ONLY_RECORDS:
            prev_ts = ts
            continue
        if rec in AUTO_RECORDS:
            prev_ts = ts
            continue
        if rec == "RecordHule":
            hules = data.get("hules") or []
            if isinstance(hules, list) and hules:
                for h in hules:
                    add_move(int(h.get("seat", 0)), rec, ts, h, note="和了")
            else:
                add_move(0, rec, ts, data, note="和了")
            prev_ts = ts
            continue
        if rec == "RecordNoTile":
            players = data.get("players") or []
            for p in players:
                add_move(int(p.get("seat", 0)), rec, ts, p, note="九種九牌")
            prev_ts = ts
            continue

        seat = data.get("seat")
        if seat is None:
            if isinstance(data, dict) and data.get("gang_infos") is not None:
                gi = data.get("gang_infos") or []
                for g in gi if isinstance(gi, list) else [gi]:
                    if isinstance(g, dict) and g.get("seat") is not None:
                        add_move(int(g["seat"]), rec, ts, g, note="三麻槍槓")
                prev_ts = ts
                continue
            # records without seat info are treated as plain timeline events
            texts.append(f"skip record without seat: {rec} @{ts}ms")
            prev_ts = ts
            continue

        seat = int(seat)
        note = ""
        # attach client-reported timeuse (s) when the twin user_input exists
        op = input_.get("operation") if isinstance(input_, dict) else None
        if isinstance(op, dict) and op.get("timeuse") is not None:
            try:
                moves[-1]["timeuse_s"] = float(op["timeuse"]) if moves else None
            except (TypeError, ValueError):
                pass
        if rec == "RecordChiPengGang":
            t = data.get("type")
            note = CPG_LABELS.get(t, f"鳴牌({t})") if t is not None else "鳴牌"
        elif rec == "RecordAnGangAddGang":
            t = data.get("type")
            note = ANKAN_LABELS.get(t, f"槓({t})") if t is not None else "槓"
        elif rec == "RecordDiscardTile" and data.get("is_liqi"):
            note = "立直宣言"
        elif rec == "RecordDiscardTile" and data.get("moqie"):
            note = "模切"
        add_move(seat, rec, ts, data, note)

    if not moves:
        return [], "時間軸中未找到任何可解析的動作"
    return moves, None


# --------------------------------------------------------------------------- #
# 統計
# --------------------------------------------------------------------------- #

def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * q
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def player_stats(moves: list[dict], player_count: int) -> list[dict]:
    stats = []
    for seat in range(player_count):
        rows = [m for m in moves if m["seat"] == seat]
        thinks = sorted(
            float(m["think_ms"]) / 1000.0
            for m in rows
            if m["think_ms"] is not None and m["think_ms"] >= 0
        )
        s = {
            "seat": seat,
            "player": rows[0]["player"] if rows else f"座{seat + 1}",
            "count": len(rows),
            "total_s": sum(thinks),
            "mean_s": statistics.fmean(thinks) if thinks else 0.0,
            "median_s": quantile(thinks, 0.5) if thinks else 0.0,
            "p25_s": quantile(thinks, 0.25) if thinks else 0.0,
            "p75_s": quantile(thinks, 0.75) if thinks else 0.0,
            "p90_s": quantile(thinks, 0.9) if thinks else 0.0,
            "p95_s": quantile(thinks, 0.95) if thinks else 0.0,
            "max_s": max(thinks) if thinks else 0.0,
            "moqie": sum(1 for m in rows if m["moqie"]),
            "liqi": sum(1 for m in rows if m["liqi"]),
            "calls": sum(1 for m in rows if m["note"] in ("吃", "碰", "槓", "暗槓", "加槓")),
        }
        stats.append(s)
    return stats


# --------------------------------------------------------------------------- #
# SVG 圖表
# --------------------------------------------------------------------------- #

W, H = 860, 400


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


def svg_header(title: str, height: int) -> str:
    return (f'<svg viewBox="0 0 {W} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Microsoft YaHei, Segoe UI, sans-serif">'
            f'<text x="8" y="20" font-size="13" font-weight="bold" fill="#333">{esc(title)}</text>')


def y_axis(svg: list[str], ymax: float, y0: float, plot_h: float, x0: float, label: str) -> None:
    for step in (5, 10, 20, 30, 60, 120):
        if ymax / step <= 8:
            break
    n = int(math.ceil(ymax / step))
    for i in range(n + 1):
        val = i * step
        y = y0 + plot_h - (val / ymax) * plot_h
        svg.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{W - 16}" y2="{y:.1f}" '
                   f'stroke="#eee" stroke-width="1"/>')
        svg.append(f'<text x="{x0 - 6}" y="{y + 3:.1f}" font-size="10" fill="#888" '
                   f'text-anchor="end">{val}s</text>')
    svg.append(f'<text x="{x0 - 6}" y="{y0 - 8}" font-size="10" fill="#888" '
               f'text-anchor="end">{esc(label)}</text>')


def chart_bar_summary(stats: list[dict]) -> str:
    h = 300
    lines = [svg_header("平均 / 中位數 思考時間(秒)", h)]
    names = [s["player"] for s in stats]
    n = len(stats)
    bw = 64
    gap = 130
    base_x = 70
    maxv = max(max(s["mean_s"], s["median_s"]) for s in stats) * 1.15 or 1.0
    y0, plot_h = 60, h - 90
    y_axis(lines, maxv, y0, plot_h, base_x, "秒")
    for i, s in enumerate(stats):
        x = base_x + 40 + i * gap
        mean_h = (s["mean_s"] / maxv) * plot_h
        med_h = (s["median_s"] / maxv) * plot_h
        c = PLAYER_COLORS[i % len(PLAYER_COLORS)]
        lines.append(f'<rect x="{x - bw / 2}" y="{y0 + plot_h - mean_h:.1f}" width="{bw}" '
                     f'height="{mean_h:.1f}" fill="{c}" opacity="0.85"/>')
        lines.append(f'<rect x="{x - bw / 2 + bw + 6}" y="{y0 + plot_h - med_h:.1f}" width="{bw * 0.55}" '
                     f'height="{med_h:.1f}" fill="{c}" opacity="0.45"/>')
        lines.append(f'<text x="{x}" y="{y0 + plot_h - mean_h - 6:.1f}" font-size="11" '
                     f'text-anchor="middle" fill="#333">{s["mean_s"]:.1f}s</text>')
        lines.append(f'<text x="{x + bw * 0.55 / 2 + 3}" y="{y0 + plot_h - med_h - 6:.1f}" '
                     f'font-size="10" text-anchor="middle" fill="#555">{s["median_s"]:.1f}s</text>')
        lines.append(f'<text x="{x}" y="{h - 12}" font-size="12" text-anchor="middle" '
                     f'fill="{c}" font-weight="bold">{esc(names[i])}</text>')
    lines.append(f'<rect x="{base_x + 40 - bw / 2}" y="38" width="{bw}" height="10" fill="#777" opacity="0.85"/>'
                 f'<text x="{base_x + 40 + bw / 2 + 8}" y="47" font-size="10" fill="#555">平均</text>')
    lines.append(f'<rect x="{base_x + 40 + bw + 6}" y="38" width="{bw * 0.55}" height="10" fill="#777" opacity="0.45"/>'
                 f'<text x="{base_x + 40 + bw * 1.3}" y="47" font-size="10" fill="#555">中位數</text>')
    lines.append("</svg>")
    return "".join(lines)


def chart_boxplot(stats: list[dict]) -> str:
    h = 320
    lines = [svg_header("思考時間分佈(箱型圖,whisker = p10/p90,點 = 離群值)", h)]
    n = len(stats)
    bp_w = 110
    maxv = max(s["p95_s"] for s in stats) * 1.15 or 1.0
    y0, plot_h = 50, h - 100
    base_x = 70
    y_axis(lines, maxv, y0, plot_h, base_x, "秒")
    for i, s in enumerate(stats):
        cx = base_x + 40 + i * 130
        c = PLAYER_COLORS[i % len(PLAYER_COLORS)]
        q1, med, q3 = s["p25_s"], s["median_s"], s["p75_s"]
        lo, hi = s["p10"] if "p10" in s else q1 - 1.5 * (q3 - q1), s["p90_s"]
        y_lo = y0 + plot_h - (lo / maxv) * plot_h
        y_q1 = y0 + plot_h - (q1 / maxv) * plot_h
        y_med = y0 + plot_h - (med / maxv) * plot_h
        y_q3 = y0 + plot_h - (q3 / maxv) * plot_h
        y_hi = y0 + plot_h - (hi / maxv) * plot_h
        lines.append(f'<line x1="{cx}" y1="{y_lo:.1f}" x2="{cx}" y2="{y_hi:.1f}" stroke="{c}" stroke-width="2"/>')
        lines.append(f'<rect x="{cx - bp_w / 2}" y="{y_q3:.1f}" width="{bp_w}" height="{max(y_q1 - y_q3, 2):.1f}" '
                     f'fill="{c}" opacity="0.35" stroke="{c}" stroke-width="1.5"/>')
        lines.append(f'<line x1="{cx - bp_w / 2}" y1="{y_med:.1f}" x2="{cx + bp_w / 2}" y2="{y_med:.1f}" '
                     f'stroke="{c}" stroke-width="2.5"/>')
        lines.append(f'<line x1="{cx - bp_w / 4}" y1="{y_q3:.1f}" x2="{cx + bp_w / 4}" y2="{y_q3:.1f}" stroke="{c}"/>')
        lines.append(f'<line x1="{cx - bp_w / 4}" y1="{y_q1:.1f}" x2="{cx + bp_w / 4}" y2="{y_q1:.1f}" stroke="{c}"/>')
        lines.append(f'<text x="{cx}" y="{y_med - (y_q3 - y_med) / 2 - 4:.1f}" font-size="10" '
                     f'text-anchor="middle" fill="#333">{med:.1f}s</text>')
        lines.append(f'<text x="{cx}" y="{h - 12}" font-size="12" text-anchor="middle" fill="{c}" '
                     f'font-weight="bold">{esc(s["player"])}</text>')
    lines.append("</svg>")
    return "".join(lines)


def chart_histograms(moves: list[dict], stats: list[dict], bin_s: float = 2.0, cap_s: float = 40.0) -> str:
    h = 60 + len(stats) * 78
    lines = [svg_header(f"每打思考時間直方圖(2s 一柱,> {cap_s:.0f}s 併入最後一柱)", h)]
    x0, base_y = 60, 46
    plot_w = W - x0 - 30
    nbins = int(math.ceil(cap_s / bin_s))
    for i, s in enumerate(stats):
        y0 = base_y + i * 78
        c = PLAYER_COLORS[s["seat"] % len(PLAYER_COLORS)]
        rows = [m for m in moves if m["seat"] == s["seat"] and m["think_ms"] is not None]
        counts = [0] * nbins
        for m in rows:
            v = max(0.0, min(m["think_ms"] / 1000.0, cap_s - 1e-6))
            counts[min(int(v / bin_s), nbins - 1)] += 1
        cmax = max(counts) or 1
        bar_h = 46
        lines.append(f'<text x="{x0 - 8}" y="{y0 + 30}" font-size="11" fill="{c}" '
                     f'font-weight="bold" text-anchor="end">{esc(s["player"])}</text>')
        for b, cnt in enumerate(counts):
            bh = (cnt / cmax) * bar_h
            x = x0 + b * (plot_w / nbins)
            w = plot_w / nbins - 1.5
            lines.append(f'<rect x="{x:.1f}" y="{y0 + bar_h - bh:.1f}" width="{w:.1f}" height="{bh:.1f}" '
                         f'fill="{c}" opacity="0.75"/>')
        lines.append(f'<line x1="{x0}" y1="{y0 + bar_h + 3}" x2="{x0 + plot_w}" y2="{y0 + bar_h + 3}" stroke="#ccc"/>')
        for t in range(0, int(cap_s) + 1, 10):
            x = x0 + (t / cap_s) * plot_w
            lines.append(f'<text x="{x:.0f}" y="{y0 + bar_h + 16}" font-size="9" fill="#999" '
                         f'text-anchor="middle">{t}s</text>')
    lines.append("</svg>")
    return "".join(lines)


def chart_scatter(moves: list[dict], stats: list[dict]) -> str:
    h = 320
    lines = [svg_header("每打思考時間走勢(按行動序;>60s 標為空心圈)", h)]
    n_moves = len(moves)
    x0, y0 = 60, 44
    plot_w, plot_h = W - x0 - 20, h - 110
    cap = 60.0
    y_axis(lines, cap, y0, plot_h, x0, "秒")
    for i, s in enumerate(stats):
        c = PLAYER_COLORS[s["seat"] % len(PLAYER_COLORS)]
        rows = [(m["idx"], m["think_ms"] / 1000.0)
                for m in moves if m["seat"] == s["seat"] and m["think_ms"] is not None]
        pts = []
        for idx, v in rows:
            x = x0 + ((idx - 1) / max(n_moves - 1, 1)) * plot_w
            y = y0 + plot_h - (min(v, 100) / cap) * plot_h
            if v > cap:
                pts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="none" stroke="{c}" stroke-width="1.5"/>')
            else:
                pts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{c}" opacity="0.8"/>')
        lines.append("".join(pts))
        lines.append(f'<text x="{W - 200}" y="{y0 + 12 + i * 15}" font-size="11" fill="{c}">'
                     f'● {esc(s["player"])}</text>')
    lines.append("</svg>")
    return "".join(lines)


def think_color(sec: float) -> str:
    if sec < 3:
        return "#4caf50"
    if sec < 6:
        return "#9ccc65"
    if sec < 12:
        return "#fbc02d"
    if sec < 25:
        return "#f57c00"
    return "#e53935"


def chart_rhythm(moves: list[dict], stats: list[dict], game_len_s: float) -> str:
    h = 40 + len(stats) * 46
    lines = [svg_header("全場節奏條(每格一打:綠<3s 黃<12s 橙<25s 紅≥25s;白=模切)", h)]
    x0, y0 = 60, 34
    plot_w = W - x0 - 20
    dur = max(game_len_s, 1.0)
    for i, s in enumerate(stats):
        y = y0 + i * 46
        c = PLAYER_COLORS[s["seat"] % len(PLAYER_COLORS)]
        lines.append(f'<rect x="{x0}" y="{y}" width="{plot_w}" height="22" fill="#f4f4f4" rx="3"/>')
        lines.append(f'<text x="{x0 - 8}" y="{y + 15}" font-size="11" fill="{c}" '
                     f'font-weight="bold" text-anchor="end">{esc(s["player"])}</text>')
        for m in moves:
            if m["seat"] != s["seat"]:
                continue
            x1 = x0 + (m["ts_ms"] / 1000.0 / dur) * plot_w
            w = max(plot_w / (len(moves) + 0.0), 3.0)
            if m["moqie"]:
                fill = "#ffffff"
                stroke = "#bbb"
            else:
                fill = think_color((m["think_ms"] or 0) / 1000.0)
                stroke = "none"
            lines.append(f'<rect x="{x1:.1f}" y="{y + 1}" width="{min(w, plot_w - x1 + x0):.1f}" '
                         f'height="20" fill="{fill}" stroke="{stroke}" stroke-width="0.8" rx="1.5"/>')
    for t in range(0, int(dur) + 1, max(60, int(dur // 8))):
        x = x0 + (t / dur) * plot_w
        lines.append(f'<text x="{x:.0f}" y="{h - 6}" font-size="9" fill="#999" '
                     f'text-anchor="middle">{t // 60}m{t % 60:02d}</text>')
    lines.append("</svg>")
    return "".join(lines)


# --------------------------------------------------------------------------- #
# 報告
# --------------------------------------------------------------------------- #

def build_report(moves: list[dict], stats: list[dict], meta: dict) -> str:
    names = [s["player"] for s in stats]
    rows_html = []
    for m in moves:
        think = f'{m["think_ms"] / 1000.0:.1f}s' if m["think_ms"] is not None else "-"
        gap = f'{m["gap_self_ms"] / 1000.0:.1f}s' if m["gap_self_ms"] is not None else "-"
        flag = []
        if m["moqie"]:
            flag.append("模切")
        if m["liqi"]:
            flag.append("立直")
        if m["note"]:
            flag.append(m["note"])
        rows_html.append(
            f"<tr><td>{m['idx']}</td><td>{esc(m['kyoku'])}</td><td>{esc(m['player'])}</td>"
            f"<td>{esc(m['type'])}</td><td>{esc(m['tile'] or '-')}</td>"
            f"<td>{think}</td><td>{gap}</td><td>{esc(' / '.join(flag) or '-')}</td>"
            f"<td>{m['ts_ms'] / 1000:.0f}s</td></tr>"
        )
    stats_html = []
    for s in stats:
        stats_html.append(
            f"<tr><td><b>{esc(s['player'])}</b></td><td>{s['count']}</td>"
            f"<td>{s['total_s']:.0f}</td><td>{s['mean_s']:.1f}</td><td>{s['median_s']:.1f}</td>"
            f"<td>{s['p25_s']:.1f} ~ {s['p75_s']:.1f}</td><td>{s['p90_s']:.1f}</td>"
            f"<td>{s['max_s']:.1f}</td><td>{s['moqie']}</td><td>{s['liqi']}</td><td>{s['calls']}</td></tr>"
        )
    game_len_s = max((m["ts_ms"] / 1000.0 for m in moves), default=0.0)
    game_t = time.strftime("%M:%S", time.gmtime(game_len_s))
    head = [f"<h1>思考時間分析</h1>",
            f"<p class='meta'>牌譜 <code>{esc(meta.get('paipu_id', '-'))}</code> · 全場遊戲時間 "
            f"{game_t} · 總動作 {len(moves)} 打</p>"]
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>思考時間分析</title>
<style>
 body {{ font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; margin: 24px; color: #222; }}
 h1 {{ font-size: 22px; }} .meta {{ color: #666; margin-bottom: 20px; }}
 h2 {{ font-size: 16px; margin: 26px 0 6px; border-left: 4px solid #3a7bd5; padding-left: 8px; }}
 table {{ border-collapse: collapse; font-size: 12px; margin: 8px 0 16px; }}
 th, td {{ border: 1px solid #ddd; padding: 3px 8px; text-align: center; }}
 th {{ background: #f0f4f8; }} 
 .wrap {{ max-height: 420px; overflow: auto; border: 1px solid #ddd; }}
 svg {{ width: 100%; max-width: 900px; height: auto; }}
</style></head><body>
{''.join(head)}
<h2>玩家匯總</h2>
<table><tr><th>玩家</th><th>動作數</th><th>總思考</th><th>平均</th><th>中位數</th>
<th>IQR (p25~p75)</th><th>p90</th><th>最大</th><th>模切</th><th>立直</th><th>鳴牌/槓</th></tr>
{''.join(stats_html)}</table>
<h2>平均 / 中位數</h2>{chart_bar_summary(stats)}
<h2>分佈(箱型圖)</h2>{chart_boxplot(stats)}
<h2>直方圖</h2>{chart_histograms(moves, stats)}
<h2>時間走勢</h2>{chart_scatter(moves, stats)}
<h2>全場節奏條</h2>{chart_rhythm(moves, stats, game_len_s)}
<h2>逐打明細</h2>
<div class="wrap"><table><tr><th>#</th><th>局</th><th>玩家</th><th>動作</th><th>牌</th>
<th>思考</th><th>距自己上打</th><th>備註</th><th>對局時間</th></tr>
{''.join(rows_html)}</table></div>
<p class="meta">思考時間 = 本動作與上一條伺服器記錄的間隔。含小幅網路延遲;鳴牌含響應窗口;
「不鳴牌的 pass」官方不記錄,不在表中;舊版牌譜無時間戳。</p>
</body></html>"""


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def fetch_timeline(share_url: str, service_url: str) -> tuple[list | None, list | None, str]:
    """POST + poll + GET result/timeline. Returns (names, timeline, paipu_id)."""
    service_url = service_url.rstrip("/")
    created = mjsoul_fetch._request(
        f"{service_url}/api/v1/desktop/requests",
        method="POST",
        body={"share_url": share_url},
    )
    request_id = str(created.get("request_id") or "").strip()
    token = str(created.get("request_token") or "").strip()
    if not request_id or not token:
        raise RuntimeError("paipu service did not return a request id / token")

    payload = created
    deadline = time.monotonic() + 900.0
    while True:
        state = str(payload.get("status") or "").strip()
        print(f"[mjsoul] {state}", flush=True)
        if state == "ready":
            break
        if state in mjsoul_fetch.TERMINAL_BAD:
            err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            detail = " ".join(str(x) for x in (err.get("code"), err.get("message")) if x)
            raise RuntimeError(f"paipu fetch {state}: {detail or 'unknown error'}")
        if time.monotonic() > deadline:
            raise RuntimeError("timed out waiting for the paipu service")
        try:
            poll_ms = int(payload.get("poll_after_ms") or 1000)
        except (TypeError, ValueError):
            poll_ms = 1000
        time.sleep(min(max(poll_ms / 1000.0, 0.25), 5.0))
        rid = urllib.parse.quote(request_id, safe="")
        payload = mjsoul_fetch._request(f"{service_url}/api/v1/requests/{rid}", token=token)

    rid = urllib.parse.quote(request_id, safe="")
    result = mjsoul_fetch._request(
        f"{service_url}/api/v1/requests/{rid}/result", token=token, timeout=60.0
    )
    tl = mjsoul_fetch._request(
        f"{service_url}/api/v1/requests/{rid}/timeline", token=token, timeout=60.0
    )
    paipu_id = ""
    m = urllib.parse.parse_qs(urllib.parse.urlparse(share_url).query).get("paipu")
    if m:
        paipu_id = str(m[0]).split("_")[0]
    return result.get("name"), tl.get("timeline"), paipu_id


def main() -> int:
    ap = argparse.ArgumentParser(
        description="每打思考時間分析 + 可視化(雀魂牌譜,timeline 端點)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("-u", "--url", help="雀魂分享連結或 paipu id")
    src.add_argument("-f", "--file", help="已存好的 timeline JSON 檔案")
    ap.add_argument("--paipu-service", default=None,
                    help="本地 tensoul 服務位址(預設:JP 服務 2563;game.maj-soul.com "
                         "的 CN 連結自動改用 CN 服務 2564 並以 CN token 登入)")
    ap.add_argument("--keep-paipu-service", action="store_true",
                    help="跑完保留 tensoul 服務(批量用)")
    ap.add_argument("-o", "--out", default=str(OUT_DIR), help="輸出目錄")
    ap.add_argument("--no-open", action="store_true", help="不自動打開報告")
    args = ap.parse_args()

    names: list | None = None
    timeline: list | None = None
    paipu_id = ""
    paipu_proc = None

    if args.url:
        print(f"[think-time] fetching {args.url}")
        try:
            service_url, svc_env = mjsoul_fetch.resolve_service(
                args.url, args.paipu_service
            )
            print(f"[think-time] using paipu service {service_url}", flush=True)
            paipu_proc, started = mjsoul_fetch.ensure_local_service(
                service_url,
                env=svc_env,
                log_path=OUT_DIR / "tensoul_service.log",
                print_fn=lambda s: print(f"[mjsoul] {s}", flush=True),
            )
            names, timeline, paipu_id = fetch_timeline(args.url, service_url)
        except Exception as exc:
            if paipu_proc:
                mjsoul_fetch.stop_local_service(paipu_proc)
                print("[mjsoul] local paipu service stopped", flush=True)
            print(f"[think-time] FAILED: {exc}", file=sys.stderr)
            return 3
        if started and args.keep_paipu_service:
            print("[mjsoul] keeping the local paipu service running "
                  "(--keep-paipu-service)", flush=True)
        elif started:
            mjsoul_fetch.stop_local_service(paipu_proc)
            print("[mjsoul] local paipu service stopped", flush=True)
    else:
        with open(args.file, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        names = saved.get("names") if isinstance(saved, dict) else None
        timeline = saved.get("timeline") if isinstance(saved, dict) else None
        paipu_id = Path(args.file).stem

    moves, err = parse_moves(names, timeline)
    if err:
        print(f"[think-time] {err}", file=sys.stderr)
        return 2

    stats = player_stats(moves, len(names) if names else max(m["seat"] for m in moves) + 1)

    out_dir = Path(args.out) / f"thinktime_{paipu_id or 'game'}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.html"
    csv_path = out_dir / "think_times.csv"
    json_path = out_dir / "summary.json"

    report = build_report(moves, stats, {"paipu_id": paipu_id})
    report_path.write_text(report, encoding="utf-8")

    import csv as _csv
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.writer(fh)
        w.writerow(["idx", "kyoku", "seat", "player", "type", "tile", "think_s",
                    "gap_self_s", "moqie", "liqi", "note", "ts_s"])
        for m in moves:
            w.writerow([
                m["idx"], m["kyoku"], m["seat"], m["player"], m["type"],
                m["tile"] or "", (m["think_ms"] / 1000.0) if m["think_ms"] is not None else "",
                (m["gap_self_ms"] / 1000.0) if m["gap_self_ms"] is not None else "",
                int(m["moqie"]), int(m["liqi"]), m["note"], m["ts_ms"] / 1000.0,
            ])
    json_path.write_text(
        json.dumps({"paipu_id": paipu_id, "players": stats, "moves": len(moves)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[think-time] moves: {len(moves)}, report: {report_path}")
    for s in stats:
        print(f"  {s['player']:<12} n={s['count']:<3} avg={s['mean_s']:6.1f}s "
              f"med={s['median_s']:5.1f}s p90={s['p90_s']:6.1f}s max={s['max_s']:6.1f}s "
              f"moqie={s['moqie']}")
    if not args.no_open:
        try:
            os.startfile(str(report_path))  # type: ignore[attr-defined]
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())