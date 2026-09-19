#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Mortal replay reviewer.

Runs the official `mjai-reviewer` (https://github.com/killerducky/mjai-reviewer)
with a *custom* Mortal `.pth` model, and renders the same HTML report UI as
https://mjai.ekyu.moe .

Supported inputs
----------------
* Tenhou URL              -> ``-u https://tenhou.net/0/?log=...&tw=2``
* Mahjong Soul share URL  -> ``-u https://game.maj-soul.com/1/?paipu=...``
  (fetched + converted login-free by the bundled ``mjsoul_fetch.py``; the seat
  is auto-detected from the ``_a<account>`` suffix of the link)
* Mahjong Soul log file   -> ``-i log.json -a <seat>`` (export it yourself with
  the bundled ``downloadlogs.js`` Tampermonkey script)
* Any tenhou.net/6 JSON   -> ``-i file.json -a <seat>``

Examples
--------
    # Tenhou game with the finetuned model
    python review.py -u "https://tenhou.net/0/?log=2019050417gm-0029-0000-4f2a8622&tw=2"

    # Mahjong Soul share link (no account needed)
    python review.py -u "https://game.maj-soul.com/1/?paipu=260914-...._a263619576"

    # pick a model / only some kyokus / JSON output
    python review.py -u "..." -m "mortal/pretrained/mortal.pth" -k E1,E3 --json
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import mjsoul_fetch

# The console on zh-TW/zh-CN Windows defaults to cp950/cp936, which cannot encode
# every player name that shows up in a Mahjong Soul log. Force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # .../Mortal-main
MORTAL_DIR = ROOT / "mortal"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WRAPPER = HERE / "mortal-wrapper" / "target" / "release" / "mortal-wrapper.exe"
REVIEWER_DIR = HERE / "mjai-reviewer-master"
REVIEWER = REVIEWER_DIR / "target" / "release" / "mjai-reviewer.exe"
OUT_DIR = HERE / "out"

DEFAULT_MODEL = MORTAL_DIR / "output" / "my_finetuned_model" / "phase2_selfplay_step325000.pth"
DEFAULT_GRP = MORTAL_DIR / "pretrained" / "grp.pth"


def describe_model(path: Path) -> str:
    """Best-effort identification of a checkpoint (training step + tag).

    `mortal.pth` is the *current* working model; `best.pth` is the last snapshot
    that won a 1v3 self-play evaluation.  They are different models, so printing
    the step count makes it obvious which one a given report came from.
    """
    try:
        import torch  # imported lazily: a missing torch must not break review
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
        bits = []
        steps = ckpt.get("steps")
        if steps is not None:
            bits.append(f"steps={int(steps):,}")
        cfg = ckpt.get("config")
        if isinstance(cfg, dict) and cfg.get("tag"):
            bits.append(f"tag={cfg['tag']}")
        return "  (" + ", ".join(bits) + ")" if bits else ""
    except Exception:
        return ""


def write_cfg(model: Path, grp: Path, dest: Path) -> Path:
    """Write a minimal inference config (utf-8, no BOM: toml chokes on BOM)."""
    text = (
        "[control]\n"
        f'state_file = "{model.as_posix()}"\n'
        "\n"
        "[grp]\n"
        f'state_file = "{grp.as_posix()}"\n'
        "\n"
        "[grp.network]\n"
        "hidden_size = 64\n"
        "num_layers = 2\n"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return dest


def preflight(args, in_file: str | None, player_id: int | None,url=None) -> None:
    problems = []
    if not REVIEWER.is_file():
        problems.append(
            f"mjai-reviewer not built: {REVIEWER}\n"
            f"    build it with:  cd \"{REVIEWER_DIR}\" && cargo build --release"
        )
    if not WRAPPER.is_file():
        problems.append(
            f"mortal-wrapper not built: {WRAPPER}\n"
            f"    build it with:  cd \"{HERE / 'mortal-wrapper'}\" && cargo build --release"
        )
    if not VENV_PY.is_file():
        problems.append(f"python venv not found: {VENV_PY}")
    if not args.model.is_file():
        problems.append(f"model not found: {args.model}")
    if not args.grp.is_file():
        problems.append(f"grp weights not found: {args.grp}")
    if not in_file and not url:
        problems.append("you must pass either -u/--url (Tenhou or Mahjong Soul) or -i/--in-file")
    if in_file and player_id is None and not args.player_name:
        problems.append(
            "-a/--player-id (or -n/--player-name) is required for -i/--in-file "
            "(only Mahjong Soul share links carry the seat)"
        )
    if problems:
        print("Preflight check failed:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Review a Tenhou / Mahjong Soul log with a custom Mortal .pth model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_argument_group("input")
    src.add_argument("-u", "--url",
                     help="Tenhou log URL or Mahjong Soul share URL (…?paipu=…)")
    src.add_argument("-i", "--in-file", help="tenhou.net/6 format log file")
    src.add_argument("-a", "--player-id", type=int, choices=[0, 1, 2, 3],
                     help="seat to review: 0=East, then 1=right, 2=across, 3=left")
    src.add_argument("-n", "--player-name", help="review the player with this name instead of --player-id")
    src.add_argument("--paipu-service", default=mjsoul_fetch.DEFAULT_SERVICE_URL,
                     help="Mahjong Soul paipu fetch service (default: %(default)s)")

    ap.add_argument("-m", "--model", type=Path, default=DEFAULT_MODEL,
                    help=f"custom Mortal .pth to review with (default: {DEFAULT_MODEL.name})")
    ap.add_argument("--grp", type=Path, default=DEFAULT_GRP, help="GRP weights (.pth)")

    out = ap.add_argument_group("output")
    out.add_argument("-o", "--out-file", type=Path, help="output report file (.html or .json)")
    out.add_argument("--json", action="store_true", help="write JSON instead of an HTML report")
    out.add_argument("--lang", default="zh", choices=["en", "ja", "zh", "ko"],
                     help="report language (default: zh)")
    out.add_argument("--show-rating", action="store_true", help="include the rating")
    out.add_argument("--no-open", action="store_true", help="do not open the report in the browser")
    out.add_argument("--anonymous", action="store_true", help="hide player names")
    out.add_argument("-k", "--kyokus", help='only review these kyokus, e.g. "E1,E4,S3.1"')
    ap.add_argument("-t", "--temperature", default="0.1", help="softmax temperature (default 0.1)")
    ap.add_argument("-v", "--verbose", action="store_true", help="verbose mjai-reviewer logs")

    args = ap.parse_args()

    # resolve model paths up front: mjai-reviewer runs with cwd = REVIEWER_DIR, so
    # the paths baked into the generated config must be absolute.
    args.model = Path(args.model).resolve()
    args.grp = Path(args.grp).resolve()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- resolve input ---------------------------------------------------- #
    url = args.url
    in_file = args.in_file
    player_id = args.player_id

    if url and mjsoul_fetch.is_mjsoul_url(url):
        print(f"[review] Mahjong Soul link detected -> fetching via {args.paipu_service}")
        try:
            result, path = mjsoul_fetch.fetch_tenhou(
                url,
                OUT_DIR / "mjsoul_tenhou.json",
                service_url=args.paipu_service,
                status_callback=lambda s: print(f"[mjsoul] {s}", flush=True),
            )
        except RuntimeError as exc:
            print(f"[review] failed to fetch paipu: {exc}", file=sys.stderr)
            return 3
        in_file = str(path)
        url = None
        print(f"[review] converted log -> {path}")
        if player_id is None and isinstance(result.get("_target_actor"), int):
            player_id = result["_target_actor"]
            names = result.get("name") or []
            who = names[player_id] if player_id < len(names) else "?"
            print(f"[review] seat auto-detected from link: {player_id} ({who})")

    preflight(args, in_file, player_id, url)

    cfg = write_cfg(args.model, args.grp, OUT_DIR / "config_review.toml")

    # NB: mjai-reviewer runs with cwd = REVIEWER_DIR, so paths must be absolute.
    if args.out_file:
        report = Path(args.out_file).resolve()
    else:
        report = (OUT_DIR / ("report" + (".json" if args.json else ".html"))).resolve()

    cmd = [
        str(REVIEWER),
        "-e", "mortal",
        "--mortal-exe", str(WRAPPER),
        "--mortal-cfg", str(cfg),
        "--temperature", str(args.temperature),
        "--lang", args.lang,
        "-o", str(report),
    ]
    if url:
        cmd += ["-u", url]
    else:
        cmd += ["-i", str(Path(in_file).resolve())]
    if player_id is not None:
        cmd += ["-a", str(player_id)]
    if args.player_name:
        cmd += ["-n", args.player_name]
    if args.kyokus:
        cmd += ["-k", args.kyokus]
    if args.json:
        cmd.append("--json")
    if args.show_rating:
        cmd.append("--show-rating")
    if args.anonymous:
        cmd.append("--anonymous")
    if args.no_open:
        cmd.append("--no-open")
    if args.verbose:
        cmd.append("--verbose")

    env = dict(os.environ)
    env["MORTAL_PYTHON"] = str(VENV_PY)
    env["MORTAL_HOME"] = str(MORTAL_DIR)

    print(f"[review] model : {args.model}{describe_model(args.model)}")
    print(f"[review] report: {report}")
    print("[review] running mjai-reviewer ...", flush=True)

    proc = subprocess.run(cmd, cwd=str(REVIEWER_DIR), env=env)
    if proc.returncode != 0:
        print(f"[review] mjai-reviewer failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    print(f"[review] done -> {report}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
