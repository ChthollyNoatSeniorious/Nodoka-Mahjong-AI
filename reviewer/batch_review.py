#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量跑譜:一次 n 局雀魂牌譜 → 逐局複審 + 思考時間 + n 局平均值指標。

輸入:一個文字檔,每行一條雀魂分享連結(空行 / # 開頭的行忽略),或 -u 重複給。

每局輸出(history_record 下分兩個資料夾,每局以牌譜 id 建子資料夾):

    history_record/analysis/<paipu_id>/      殺手鴨複審(killerducky review.json + GUI)
        review.json      複審結果 JSON(rating / 每手 top1 一致率 / mjai_log)
        index.html + media/  Killer Mortal Reviewer 互動介面(需本地 HTTP 開啟,
                            可用本腳本 --serve;或 `cd history_record && python -m http.server`)
        tenhou.json     抓下來的 tenhou 格式牌譜(快取,重跑不重抓)
    history_record/thinking/<paipu_id>/      思考時間分析(think_time 產物)
        report.html     每打思考時間可視化(雙擊即開)
        think_times.csv / summary.json / timeline.json

外加根目錄:
    history_record/summary.json   目標玩家 n 局平均值指標(機讀)
    history_record/summary.html   n 局明細 + 平均(瀏覽器直接開)

座位:優先取分享連結的 _a<uid> 後綴自動判定(秋野花 = 該 uid 的座位);
顯式給 -a 0..3 則一律覆蓋。

每次跑把「牌譜分析」與「切牌時間」兩個 html 分開存到各自的資料夾,
重跑時已有產物會直接沿用(用 --force 重建 / --refetch 重抓數據)。

用法:
    python reviewer\\batch_review.py --list games.txt
    python reviewer\\batch_review.py -u "<連結1>" -u "<連結2>" -a 0
    python reviewer\\batch_review.py --list games.txt --serve      # 跑完起本地服務看 GUI
    python reviewer\\batch_review.py --list games.txt --keep-paipu-service
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import socketserver
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable

try:  # Windows console cp950-safe output
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import mjsoul_fetch
import review       # reuse: REVIEWER / WRAPPER / VENV_PY / DEFAULT_MODEL / write_cfg / copy_killerducky_ui
import think_time   # reuse: parse_moves / player_stats / build_report

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out" / "history_record"
ANALYZE_DIR = OUT_DIR / "analysis"
THINKING_DIR = OUT_DIR / "thinking"

INITIAL = 25000  # 雀魂起始分


# --------------------------------------------------------------------------- #
# 抓譜(每局只 POST 一次,共用 request_id 同時取 result + timeline)
# --------------------------------------------------------------------------- #

def paipu_id_from_url(share_url: str) -> str:
    m = urllib.parse.parse_qs(urllib.parse.urlparse(share_url).query).get("paipu")
    if not m:
        raise ValueError("網址沒有 paipu= 參數")
    return str(m[0]).split("_")[0]


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch_game_once(
    share_url: str,
    service_url: str,
    tenhou_path: Path,
    timeline_path: Path,
    status: Callable[[str], None] = lambda s: None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """POST /desktop/requests 一次 → poll → 同時取 /result 與 /timeline。

    寫入 tenhou.json 與 timeline.json(think_time -f 可直接吃),回傳 result dict。
    """
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
        status(state)
        if state == "ready":
            break
        if state in mjsoul_fetch.TERMINAL_BAD:
            err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            detail = " ".join(str(x) for x in (err.get("code"), err.get("message")) if x)
            raise RuntimeError(f"paipu fetch {state}: {detail or 'unknown error'}")
        if state not in mjsoul_fetch.PENDING_STATES:
            raise RuntimeError(f"paipu service returned unknown status: {state!r}")
        if time.monotonic() > deadline:
            raise RuntimeError("timed out waiting for the paipu service")
        try:
            poll_ms = int(payload.get("poll_after_ms") or 1000)
        except (TypeError, ValueError):
            poll_ms = 1000
        sleep(min(max(poll_ms / 1000.0, 0.25), 5.0))
        rid = urllib.parse.quote(request_id, safe="")
        payload = mjsoul_fetch._request(f"{service_url}/api/v1/requests/{rid}", token=token)

    rid = urllib.parse.quote(request_id, safe="")
    result = mjsoul_fetch._request(
        f"{service_url}/api/v1/requests/{rid}/result", token=token, timeout=60.0
    )
    tl = mjsoul_fetch._request(
        f"{service_url}/api/v1/requests/{rid}/timeline", token=token, timeout=60.0
    )
    if not isinstance(result.get("name"), list) or not isinstance(result.get("log"), list):
        raise RuntimeError("paipu service result is missing 'name' or 'log'")
    if "ver" not in result:
        raise RuntimeError("paipu service result is missing 'ver'")

    write_json_atomic(tenhou_path, result)
    write_json_atomic(timeline_path, {
        "paipu_id": paipu_id_from_url(share_url),
        "names": result.get("name"),
        "timeline": (tl or {}).get("timeline"),
    })
    return result


# --------------------------------------------------------------------------- #
# 複審(killerducky review.json)
# --------------------------------------------------------------------------- #

def run_reviewer(
    tenhou_path: Path,
    seat: int,
    out_json: Path,
    model: Path,
    grp: Path,
    cfg: Path,
    temperature: str,
    lang: str,
) -> int:
    cmd = [
        str(review.REVIEWER),
        "-e", "mortal",
        "--mortal-exe", str(review.WRAPPER),
        "--mortal-cfg", str(cfg),
        "--temperature", str(temperature),
        "--lang", lang,
        "-o", str(out_json.resolve()),
        "--json",
        "--no-open",
        "-i", str(tenhou_path.resolve()),
        "-a", str(seat),
    ]
    env = dict(os.environ)
    env["MORTAL_PYTHON"] = str(review.VENV_PY)
    env["MORTAL_HOME"] = str(review.ROOT / "mortal")
    proc = subprocess.run(cmd, cwd=str(review.REVIEWER_DIR), env=env)
    return proc.returncode


# --------------------------------------------------------------------------- #
# 統計
# --------------------------------------------------------------------------- #

def game_review_stats(review_json_path: Path, seat: int) -> dict:
    """從 review.json 統計目標玩家的 rating / 複審數 / top1 一致率。

    review.kyokus[].entries 主要是目標玩家的決策(另有少數對手的鳴/立直點),
    所以一律按 last_actor == seat 過濾再算一致率。
    """
    d = json.loads(review_json_path.read_text(encoding="utf-8"))
    rv = d.get("review") or {}
    entries = [
        e for ky in (rv.get("kyokus") or [])
        for e in ky.get("entries") or []
        if e.get("last_actor") == seat
    ]
    n = len(entries)
    eq = sum(1 for e in entries if e.get("is_equal"))
    return {
        "rating": rv.get("rating"),
        "total_reviewed": rv.get("total_reviewed"),
        "model_tag": rv.get("model_tag"),
        "decisions": n,
        "top1_agree": (eq / n) if n else None,
        "mjai_log": d.get("mjai_log") or [],
    }


def mjai_strength_stats(mlog: list, seat: int, final_scores: list | None = None) -> dict:
    """從 mjai_log 統計目標玩家的對局強度指標。

    final_scores:4 人最終得點(優先取抓譜 result 的 sc 欄位,最權威);
    缺省時退回最後一局的 start_kyoku.scores。
    """
    kyokus = wins = dealins = reaches = calls = ryukyoku = tenpai = 0
    last_scores: list | None = None
    for ev in mlog:
        t = ev.get("type")
        if t == "start_kyoku":
            kyokus += 1
            if ev.get("scores"):
                last_scores = ev["scores"]
        elif t == "hora":
            actor, target = ev.get("actor"), ev.get("target")
            if actor == seat:
                wins += 1
            if target == seat and actor != seat:
                dealins += 1
        elif t == "reach":
            if ev.get("actor") == seat:
                reaches += 1
        elif t in ("pon", "chi", "kakan", "ankan", "daiminkan", "chankan", "minkan"):
            if ev.get("actor") == seat:
                calls += 1
        elif t == "ryukyoku":
            ryukyoku += 1
            deltas = ev.get("deltas") or []
            if seat < len(deltas) and deltas[seat] > 0:
                tenpai += 1

    if not final_scores or len(final_scores) != 4 or any(x is None for x in final_scores):
        final_scores = last_scores
    s = {
        "kyokus": kyokus, "wins": wins, "dealins": dealins,
        "reaches": reaches, "calls": calls, "ryukyoku": ryukyoku, "tenpai": tenpai,
        "final_score": None, "score_delta": None, "rank": None, "top1": None,
        "win_rate": None, "deal_rate": None, "riichi_per_kyoku": None,
        "call_rate": None, "tenpai_rate": None, "tenpai_share": None,
    }
    if last_scores and len(last_scores) == 4 and all(x is not None for x in last_scores):
        order = sorted(range(4), key=lambda i: (-last_scores[i], i))
        rank = order.index(seat) + 1
        s.update(
            final_score=last_scores[seat],
            score_delta=last_scores[seat] - INITIAL,
            rank=rank,
            top1=(rank == 1),
        )
    if kyokus:
        s["win_rate"] = wins / kyokus
        s["deal_rate"] = dealins / kyokus
        s["riichi_per_kyoku"] = reaches / kyokus
        s["call_rate"] = calls / kyokus
    if ryukyoku:
        s["tenpai_rate"] = tenpai / ryukyoku
    return s


def target_think_stats(summary_json_path: Path, seat: int) -> dict:
    """從 thinking/<pid>/summary.json 取目標玩家的思考時間統計。"""
    d = json.loads(summary_json_path.read_text(encoding="utf-8"))
    for p in d.get("players") or []:
        if p.get("seat") == seat:
            count = int(p.get("count") or 0)
            return {
                "think_count": count,
                "think_mean_s": p.get("mean_s"),
                "think_median_s": p.get("median_s"),
                "think_p90_s": p.get("p90_s"),
                "think_max_s": p.get("max_s"),
                "moqie": int(p.get("moqie") or 0),
                "moqie_rate": (int(p.get("moqie") or 0) / count) if count else None,
            }
    return {}


# --------------------------------------------------------------------------- #
# 思考時間產物(與 think_time.py 相同格式)
# --------------------------------------------------------------------------- #

def write_thinking_outputs(out_dir: Path, names: list | None, timeline: list | None,
                           paipu_id: str) -> tuple[Path, dict]:
    moves, err = think_time.parse_moves(names, timeline)
    if err:
        raise RuntimeError(err)
    player_count = len(names) if names else max((m["seat"] for m in moves), default=-1) + 1
    stats = think_time.player_stats(moves, player_count)

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.html"
    csv_path = out_dir / "think_times.csv"
    json_path = out_dir / "summary.json"

    report_path.write_text(
        think_time.build_report(moves, stats, {"paipu_id": paipu_id}), encoding="utf-8"
    )

    import csv as _csv
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.writer(fh)
        w.writerow(["idx", "kyoku", "seat", "player", "type", "tile", "think_s",
                    "gap_self_s", "moqie", "liqi", "note", "ts_s"])
        for m in moves:
            w.writerow([
                m["idx"], m["kyoku"], m["seat"], m["player"], m["type"],
                m["tile"] or "",
                (m["think_ms"] / 1000.0) if m["think_ms"] is not None else "",
                (m["gap_self_ms"] / 1000.0) if m["gap_self_ms"] is not None else "",
                int(m["moqie"]), int(m["liqi"]), m["note"], m["ts_ms"] / 1000.0,
            ])
    summary = {"paipu_id": paipu_id, "players": stats, "moves": len(moves)}
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path, summary


# --------------------------------------------------------------------------- #
# 匯總(summary.json / summary.html)
# --------------------------------------------------------------------------- #

def _fmean(values: list) -> float | None:
    return statistics.fmean(values) if values else None


def build_averages(records: list[dict]) -> dict:
    ok = [r for r in records if r.get("ok")]
    n = len(ok)

    def col(key: str) -> list:
        return [r[key] for r in ok if r.get(key) is not None]

    agg = {
        "n_games": n,
        "n_total": len(records),
        "rating_mean": _fmean(col("rating")),
        "total_reviewed_sum": sum(col("total_reviewed")),
        "top1_agree_mean": _fmean(col("top1_agree")),
        "rank_mean": _fmean(col("rank")),
        "top1_rate": (sum(1 for r in ok if r.get("top1")) / n) if n else None,
        "score_delta_mean": _fmean(col("score_delta")),
        "win_rate_mean": _fmean(col("win_rate")),
        "deal_rate_mean": _fmean(col("deal_rate")),
        "riichi_per_kyoku_mean": _fmean(col("riichi_per_kyoku")),
        "call_rate_mean": _fmean(col("call_rate")),
        "tenpai_rate_mean": _fmean(col("tenpai_rate")),
        "tenpai_n": len(col("tenpai_rate")),
        "think_mean_s_mean": _fmean(col("think_mean_s")),
        "think_median_s_mean": _fmean(col("think_median_s")),
        "moqie_rate_mean": _fmean(col("moqie_rate")),
        "think_count_sum": sum(col("think_count")),
    }
    return agg


def _esc(s: Any) -> str:
    import html as _html
    return _html.escape(str(s), quote=False)


def _pct(v: float | None, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "-"


def _num(v: float | None, digits: int = 1) -> str:
    return f"{v:.{digits}f}" if v is not None else "-"


def chart_top1_agree(records: list[dict]) -> str:
    ok = [r for r in records if r.get("ok") and r.get("top1_agree") is not None]
    if not ok:
        return ""
    W, H = 900, 190
    x0, y0, plot_w, plot_h = 70, 46, W - 100, 100
    n = len(ok)
    parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        'font-family="Microsoft YaHei, Segoe UI, sans-serif">'
        '<text x="8" y="20" font-size="13" font-weight="bold" fill="#333">'
        '每局 top1 一致率(模型首選 = 秋野花實際出牌,%)</text>'
    ]
    for g in range(0, 101, 25):
        y = y0 + plot_h - (g / 100) * plot_h
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + plot_w}" y2="{y:.1f}" stroke="#eee"/>')
        parts.append(f'<text x="{x0 - 6}" y="{y + 3:.1f}" font-size="10" fill="#888" text-anchor="end">{g}%</text>')
    for i, r in enumerate(ok):
        x = x0 + (i + 0.5) * (plot_w / n)
        v = min(max(r["top1_agree"], 0.0), 1.0)
        bh = v * plot_h
        c = "#3a7bd5" if r.get("rank") != 1 else "#e05252"
        parts.append(f'<rect x="{x - 12}" y="{y0 + plot_h - bh:.1f}" width="24" height="{bh:.1f}" fill="{c}" opacity="0.85"/>')
        parts.append(f'<text x="{x}" y="{y0 + plot_h - bh - 5:.1f}" font-size="10" text-anchor="middle" fill="#333">{v * 100:.0f}</text>')
        parts.append(f'<text x="{x}" y="{H - 10}" font-size="10" text-anchor="middle" fill="#555">{r["idx"]}</text>')
    parts.append(f'<text x="{x0}" y="{y0 - 8}" font-size="10" fill="#888">紅 = 一位局</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_summary_html(records: list[dict], agg: dict) -> str:
    rows = []
    for r in records:
        if not r.get("ok"):
            rows.append(
                f"<tr class='bad'><td>{r['idx']}</td><td>{_esc(r['paipu_id'])}</td>"
                f"<td colspan='13'>失敗: {_esc(r.get('error') or '')}</td></tr>"
            )
            continue
        ana = (f"<a href='{_esc(r['analysis_html_rel'])}' title='killerducky GUI(需 HTTP 開啟)'>分析</a>"
               if r.get("analysis_html_rel") else "-")
        think = (f"<a href='{_esc(r['thinking_html_rel'])}'>思考</a>"
                 if r.get("thinking_html_rel") else "-")
        rows.append(
            f"<tr><td>{r['idx']}</td><td>{_esc(r['paipu_id'])}</td>"
            f"<td>{_esc(r.get('player') or '-')} ({r.get('seat', '-')})</td>"
            f"<td>{ana} / {think}</td>"
            f"<td>{_num(r.get('rating'), 4)}</td>"
            f"<td>{_pct(r.get('top1_agree'))}</td>"
            f"<td>{r.get('rank', '-')}</td>"
            f"<td>{r.get('score_delta', '-')}</td>"
            f"<td>{r.get('wins', '-')}</td><td>{r.get('dealins', '-')}</td>"
            f"<td>{r.get('reaches', '-')}</td><td>{r.get('calls', '-')}</td>"
            f"<td>{_pct(r.get('tenpai_rate'))}</td>"
            f"<td>{_num(r.get('think_mean_s'))}s</td>"
            f"<td>{_num(r.get('think_median_s'))}s</td>"
            f"<td>{_pct(r.get('moqie_rate'), 0)}</td></tr>"
        )

    av = (
        "<tr class='avg'><td>平均</td><td>" + str(agg["n_games"]) + f" / {agg['n_total']} 局</td>"
        f"<td>-</td><td>-</td>"
        f"<td>{_num(agg.get('rating_mean'), 4)}</td>"
        f"<td>{_pct(agg.get('top1_agree_mean'))}</td>"
        f"<td>{_num(agg.get('rank_mean'))}</td>"
        f"<td>{_num(agg.get('score_delta_mean'))}</td>"
        f"<td>{_pct(agg.get('win_rate_mean'))}</td>"
        f"<td>{_pct(agg.get('deal_rate_mean'))}</td>"
        f"<td>{_num(agg.get('riichi_per_kyoku_mean'))}</td>"
        f"<td>{_pct(agg.get('call_rate_mean'))}</td>"
        f"<td>{_pct(agg.get('tenpai_rate_mean'))}<br><small>({agg.get('tenpai_n')} 局有流局)</small></td>"
        f"<td>{_num(agg.get('think_mean_s_mean'))}s</td>"
        f"<td>{_num(agg.get('think_median_s_mean'))}s</td>"
        f"<td>{_pct(agg.get('moqie_rate_mean'), 0)}</td></tr>"
    )

    head = []
    if agg["n_games"]:
        head.append(f"<h1>批量跑譜彙總</h1>"
                    f"<p class='meta'>n = {agg['n_games']} 局 · 複審總數 "
                    f"{agg['total_reviewed_sum']} 手 · 思考總動作 {agg['think_count_sum']} 打<br>"
                    f"平均 rating = <b>{_num(agg['rating_mean'], 4)}</b> · "
                    f"平均 top1 一致率 = <b>{_pct(agg['top1_agree_mean'])}</b> · "
                    f"平均順位 = <b>{_num(agg['rank_mean'])}</b> · 一位率 = <b>{_pct(agg['top1_rate'])}</b></p>")
    else:
        head.append("<h1>批量跑譜彙總</h1><p class='meta'>沒有成功完成的局。</p>")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>批量跑譜彙總</title>
<style>
 body {{ font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; margin: 24px; color: #222; }}
 h1 {{ font-size: 22px; }} .meta {{ color: #666; margin-bottom: 16px; }}
 table {{ border-collapse: collapse; font-size: 12px; margin: 10px 0 20px; }}
 th, td {{ border: 1px solid #ddd; padding: 3px 8px; text-align: center; white-space: nowrap; }}
 th {{ background: #f0f4f8; }} tr.bad td {{ background: #fdecea; color: #b71c1c; }}
 tr.avg td {{ background: #fff8e1; font-weight: bold; }}
 a {{ color: #1a56db; }} svg {{ width: 100%; max-width: 900px; height: auto; }}
</style></head><body>
{''.join(head)}
<h2>逐局明細(順位 / 得失點 / 和了 / 放銃 / 立直 / 副露 / 流局聽牌 / 思考)</h2>
<table><tr><th>#</th><th>牌譜</th><th>玩家(座)</th><th>報告</th><th>rating</th>
<th>top1一致</th><th>順位</th><th>得失點</th><th>和了</th><th>放銃</th><th>立直</th>
<th>副露</th><th>聽牌率</th><th>思考平均</th><th>思考中位</th><th>模切率</th></tr>
{''.join(rows)}
{av}</table>
{chart_top1_agree(records)}
<p class="meta">top1 一致率 = 目標玩家每手實際出牌與模型首選一致的比率(按 last_actor 過濾)。
「分析」連結是 Killer Mortal Reviewer 介面,需本地 HTTP 開啟(如 <code>python -m http.server</code>
或批量腳本 <code>--serve</code>);「思考」連結雙擊即開。<br>
所有明細資料同時在 <code>summary.json</code>。</p>
</body></html>"""


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def serve_history(root_dir: Path, records: list[dict]) -> None:
    """起本地 HTTP 服務看 killerducky GUI,印出每局網址後阻塞到 Ctrl+C。"""
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(root_dir)
    )

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    print(f"\n[batch] serving history_record at http://127.0.0.1:{port}/")
    for r in records:
        if not r.get("ok") or not r.get("analysis_html_rel"):
            continue
        url = (f"http://127.0.0.1:{port}/{r['analysis_html_rel']}"
               f"?data=review.json&showMortal=1&hand=0&ply=0")
        print(f"[batch]   {r['idx']:>2}. {r['paipu_id']}  {url}")
    print("[batch] serving (Ctrl+C to stop)...", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[batch] stopped")
    finally:
        httpd.server_close()


def load_links(args) -> list[tuple[str, str | None]]:
    """Return [(url, origin)] where origin is file path or '-' for -u."""
    links: list[tuple[str, str | None]] = [(u, None) for u in args.url]
    if args.list_file:
        for raw in Path(args.list_file).read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            links.append((line, args.list_file))
    return links


def main() -> int:
    ap = argparse.ArgumentParser(
        description="批量跑譜:n 局雀魂牌譜 → 每局複審 + 思考時間 html + n 局平均指標",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_argument_group("input")
    src.add_argument("-u", "--url", action="append", default=[],
                     help="雀魂分享連結(可重複多次)")
    src.add_argument("--list", dest="list_file",
                     help="文字檔,每行一條分享連結(空行 / # 註解忽略)")
    src.add_argument("-a", "--player-id", type=int, choices=[0, 1, 2, 3],
                     help="複審座位(0=東家,向右遞增);不給則用連結 _a<uid> 自動判定")
    src.add_argument("--paipu-service", default=None,
                     help="本機 tensoul 服務位址(預設:CN 用 2564 / JP 用 2563 自動)")
    src.add_argument("--keep-paipu-service", action="store_true",
                     help="跑完保留 tensoul 服務(批量續跑用)")

    ap.add_argument("-m", "--model", type=Path, default=review.DEFAULT_MODEL,
                    help=f"複審用模型(預設 {review.DEFAULT_MODEL.name})")
    ap.add_argument("--grp", type=Path, default=review.DEFAULT_GRP)
    ap.add_argument("-t", "--temperature", default="0.1")
    ap.add_argument("--lang", default="zh", choices=["en", "ja", "zh", "ko"])

    out = ap.add_argument_group("output")
    out.add_argument("-o", "--out", type=Path, default=OUT_DIR,
                     help=f"history_record 根目錄(預設 {OUT_DIR})")
    out.add_argument("--force", action="store_true",
                     help="每局全部重建(重抓數據 + 重跑複審 + 重算思考)")
    out.add_argument("--refetch", action="store_true",
                     help="重抓 tenhou/timeline 數據(已存在的複審產物仍沿用)")
    out.add_argument("--no-analysis", action="store_true", help="跳過複審步驟")
    out.add_argument("--no-thinking", action="store_true", help="跳過思考時間步驟")
    out.add_argument("--no-open", action="store_true", help="結束後不自動開啟 summary.html")
    out.add_argument("--serve", action="store_true",
                     help="結束後起本地 HTTP 服務看 killerducky GUI(印出各局網址,Ctrl+C 停止)")

    args = ap.parse_args()
    args.model = Path(args.model).resolve()
    args.grp = Path(args.grp).resolve()

    # ---- preflight -------------------------------------------------------- #
    problems = []
    for label, p in (
        ("mjai-reviewer", review.REVIEWER),
        ("mortal-wrapper", review.WRAPPER),
        ("python venv", review.VENV_PY),
        ("model", args.model),
        ("grp", args.grp),
        ("killerducky UI", review.KD_UI_DIR),
    ):
        if not p.is_file() and not p.is_dir():
            problems.append(f"{label} not found: {p}")
    links = load_links(args)
    if not links:
        problems.append("請給 -u <連結> 或 --list <檔案>")
    if problems:
        print("Preflight check failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    OUT_DIR_LOCAL = Path(args.out)
    ANALYZE_DIR = OUT_DIR_LOCAL / "analysis"
    THINKING_DIR = OUT_DIR_LOCAL / "thinking"
    OUT_DIR_LOCAL.mkdir(parents=True, exist_ok=True)
    cfg = review.write_cfg(args.model, args.grp, OUT_DIR_LOCAL / "config_batch.toml")

    # ---- services(每種 service_url+env 只起一次,批量共用) ------------------ #
    services: dict[tuple, tuple[subprocess.Popen | None, bool]] = {}

    def get_service(url: str) -> tuple[str, dict | None]:
        service_url, svc_env = mjsoul_fetch.resolve_service(url, args.paipu_service)
        key = (service_url, tuple(sorted((svc_env or {}).items())))
        if key not in services:
            proc, started = mjsoul_fetch.ensure_local_service(
                service_url,
                env=svc_env,
                log_path=HERE / "out" / "tensoul_service.log",
                print_fn=lambda s: print(f"[mjsoul] {s}", flush=True),
            )
            services[key] = (proc, started)
            print(f"[batch] paipu service {service_url} ready", flush=True)
        return service_url, svc_env

    # ---- 逐局 ------------------------------------------------------------- #
    seen: set[str] = set()
    records: list[dict] = []
    for idx, (url, origin) in enumerate(links, start=1):
        rec: dict[str, Any] = {"idx": idx, "url": url, "ok": False,
                               "error": None, "origin": origin}
        try:
            if not mjsoul_fetch.is_mjsoul_url(url):
                raise ValueError("不是雀魂分享連結(需含 paipu=)")
            pid = paipu_id_from_url(url)
            if pid in seen:
                print(f"[batch] {idx}/{len(links)} skip {pid} (重複)")
                continue
            seen.add(pid)
            rec["paipu_id"] = pid
            print(f"\n[batch] === {idx}/{len(links)} {pid} ===", flush=True)

            ana_dir = ANALYZE_DIR / pid
            thk_dir = THINKING_DIR / pid
            tenhou_path = ana_dir / "tenhou.json"
            revjson_path = ana_dir / "review.json"
            timeline_path = thk_dir / "timeline.json"

            # 1) 抓譜(有快取就沿用)
            result: dict | None = None
            if (not args.force and not args.refetch
                    and tenhou_path.is_file() and timeline_path.is_file()):
                print(f"[batch] 沿用快取 {tenhou_path.name} + timeline")
            else:
                service_url, _ = get_service(url)
                result = fetch_game_once(
                    url, service_url, tenhou_path, timeline_path,
                    status=lambda s: print(f"[mjsoul] {s}", flush=True),
                )
                print(f"[batch] 數據就緒: {tenhou_path.name} + timeline")
            if result is None:
                result = json.loads(tenhou_path.read_text(encoding="utf-8"))
            names: list | None = result.get("name")
            seat = args.player_id if args.player_id is not None \
                else result.get("_target_actor")
            if not isinstance(seat, int) or not 0 <= seat <= 3:
                raise ValueError(
                    "無法判定複審座位:連結無 _a<uid> 後綴;請用 -a 0..3 指定"
                )
            rec["seat"] = seat
            rec["player"] = names[seat] if names and seat < len(names) else f"座{seat + 1}"
            print(f"[batch] 目標玩家: 座位 {seat} ({rec['player']})", flush=True)

            # 2) 複審 review.json + killerducky GUI
            if not args.no_analysis:
                if not args.force and revjson_path.is_file():
                    print(f"[batch] 沿用複審 {revjson_path}")
                else:
                    print("[batch] 跑 mjai-reviewer(殺手鴨複審)...", flush=True)
                    rc = run_reviewer(tenhou_path, seat, revjson_path, args.model,
                                      args.grp, cfg, args.temperature, args.lang)
                    if rc != 0:
                        raise RuntimeError(f"mjai-reviewer 退出碼 {rc}")
                    print(f"[batch] 複審完成 -> {revjson_path}")
                if revjson_path.is_file():
                    review.copy_killerducky_ui(ana_dir)
                    rec["analysis_html_rel"] = f"analysis/{pid}/index.html"
            else:
                print("[batch] --no-analysis:跳過複審")

            # 3) 思考時間
            if not args.no_thinking:
                if not args.force and (thk_dir / "report.html").is_file() \
                        and not args.refetch:
                    print(f"[batch] 沿用思考報告 {thk_dir / 'report.html'}")
                else:
                    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
                    names_tl = tl.get("names")
                    timeline = tl.get("timeline")
                    rpt, _ = write_thinking_outputs(
                        thk_dir, names_tl, timeline, pid)
                    print(f"[batch] 思考報告 -> {rpt}")
                rec["thinking_html_rel"] = f"thinking/{pid}/report.html"
            else:
                print("[batch] --no-thinking:跳過思考時間")

            # 4) 統計
            if revjson_path.is_file():
                rstats = game_review_stats(revjson_path, seat)
                rec.update({k: rstats[k] for k in
                            ("rating", "total_reviewed", "decisions", "top1_agree")})
                rec["model_tag"] = rstats["model_tag"]
                # 最終得點優先取 tenhou result 的 sc 欄位([s0,±,s1,±,s2,±,s3,±])
                sc = result.get("sc") if isinstance(result, dict) else None
                finals = None
                if isinstance(sc, list) and len(sc) >= 8:
                    finals = [sc[i] for i in range(0, 8, 2)]
                    if not all(isinstance(x, (int, float)) for x in finals):
                        finals = None
                sstats = mjai_strength_stats(rstats["mjai_log"], seat, finals)
                rec.update({k: sstats[k] for k in (
                    "kyokus", "wins", "dealins", "reaches", "calls",
                    "ryukyoku", "tenpai", "final_score", "score_delta",
                    "rank", "top1", "win_rate", "deal_rate",
                    "riichi_per_kyoku", "call_rate", "tenpai_rate")})
            if (thk_dir / "summary.json").is_file():
                rec.update(target_think_stats(thk_dir / "summary.json", seat))

            rec["ok"] = True
            print(f"[batch] 完成: rating={rec.get('rating')} "
                  f"top1一致={_pct(rec.get('top1_agree'))} "
                  f"順位={rec.get('rank', '-')} "
                  f"思考平均={_num(rec.get('think_mean_s'))}s", flush=True)
        except Exception as exc:
            rec["error"] = str(exc)
            print(f"[batch] 失敗: {exc}", file=sys.stderr, flush=True)
        finally:
            records.append(rec)

    # ---- 收尾 ------------------------------------------------------------- #
    if not args.keep_paipu_service:
        for (proc, _started) in services.values():
            mjsoul_fetch.stop_local_service(proc)
        if services:
            print("[batch] paipu service 已停止(--keep-paipu-service 可保留)")

    agg = build_averages(records)
    write_json_atomic(OUT_DIR_LOCAL / "summary.json", {
        "history_record": str(OUT_DIR_LOCAL),
        "analysis_dir": "analysis/",
        "thinking_dir": "thinking/",
        "averages": agg,
        "games": records,
    })
    summary_html = OUT_DIR_LOCAL / "summary.html"
    summary_html.write_text(build_summary_html(records, agg), encoding="utf-8")

    print("\n[batch] === 彙總 ===")
    for r in records:
        if r.get("ok"):
            print(f"  {r['idx']:>2}. {r['paipu_id']} "
                  f"{r.get('player', '?')}(座{r.get('seat', '?')}) "
                  f"rating={_num(r.get('rating'), 4)} "
                  f"top1={_pct(r.get('top1_agree'))} 順位={r.get('rank', '-')} "
                  f"{_num(r.get('think_mean_s'))}s/打")
        else:
            print(f"  {r['idx']:>2}. {r.get('paipu_id', '?')} 失敗: {r.get('error')}")
    n_ok = sum(1 for r in records if r.get("ok"))
    print(f"[batch] 完成 {n_ok}/{len(records)} 局;彙總 -> {summary_html}"
          f" 與 {OUT_DIR_LOCAL / 'summary.json'}", flush=True)

    if args.serve:
        serve_history(OUT_DIR_LOCAL, [r for r in records if r.get("ok")])
    elif not args.no_open and summary_html.is_file():
        try:
            webbrowser.open(summary_html.as_uri())
        except Exception:
            pass

    return 0 if n_ok == len(records) and records else 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)