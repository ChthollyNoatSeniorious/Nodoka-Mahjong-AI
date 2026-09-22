#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch a Mahjong Soul (雀魂) paipu by share URL and convert it to Tenhou JSON.

By default this talks to the **local self-hosted service**
(`reviewer/tensoul-main`, ninklang.tech-compatible API), which connects to the
official MahjongSoul servers directly with your own account token — no
third-party API involved:

    POST  {service}/api/v1/desktop/requests          {"share_url": <url>}
      ->  {request_id, request_token, status, poll_after_ms}
    GET   {service}/api/v1/requests/{id}             Authorization: Request <token>
      ->  {status: queued|fetching|converting|ready|failed|expired}
    GET   {service}/api/v1/requests/{id}/result      Authorization: Request <token>
      ->  Tenhou JSON: {ver, name, log, _target_actor?}

The result is the same "tenhou.net/6-ish" JSON that `mjai-reviewer -i` accepts,
and `_target_actor` (when present) is the seat decoded from the share link.

To start the local service: `cd reviewer/tensoul-main && node .`
(see `reviewer/tensoul-main/README.local.md` for the one-time token setup).

Point `service_url` elsewhere (e.g. the legacy public ninklang.tech) via the
MJSOUL_SERVICE_URL env var or the `--paipu-service` flag of review.py.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_SERVICE_URL = os.environ.get(
    "MJSOUL_SERVICE_URL", "http://127.0.0.1:2563"
)
# CN server (game.maj-soul.com) runs its own local service instance on another
# port, with CN-specific env (base URL, client version, gateway, CN token).
CN_SERVICE_URL = os.environ.get("MJSOUL_CN_SERVICE_URL", "http://127.0.0.1:2564")
USER_AGENT = "Mortal-paipu-analyzer/2.0"

PENDING_STATES = {"queued", "fetching", "retry_wait", "converting"}
TERMINAL_BAD = {"failed", "expired"}

_MJSOUL_HOSTS = ("maj-soul.com", "mahjongsoul", "mahjong-soul", "majsoul")


def detect_server(value: str) -> str:
    """Which official server a share link / paipu id belongs to.

    ``game.maj-soul.com`` (and any ``*.maj-soul.com``) is the CN server;
    everything else (``mahjongsoul.*``, bare paipu ids) is treated as JP.
    """
    low = (value or "").lower()
    try:
        host = urllib.parse.urlparse(low).hostname or ""
        if host.endswith("maj-soul.com"):
            return "cn"
    except Exception:
        pass
    if "maj-soul.com" in low:
        return "cn"
    return "jp"


def resolve_service(
    share_url: str,
    explicit_service_url: str | None,
) -> tuple[str, dict | None]:
    """Pick (service_url, child env overrides) for a paipu link.

    An explicitly user-supplied service URL always wins. Otherwise JP links use
    the default JP service and CN links use the CN service instance (with the
    CN env: base URL, client version, gateway, CN token).
    """
    if explicit_service_url:
        return explicit_service_url.rstrip("/"), None
    if detect_server(share_url) == "cn":
        return CN_SERVICE_URL, cn_service_env()
    return DEFAULT_SERVICE_URL, None


def cn_service_env() -> dict:
    """Env overrides for the CN tensoul service instance.

    CN (game.maj-soul.com) 公開牌譜需要網頁端 access_token:連線序列必須先
    ``prepareLogin{type:0, access_token}`` 再 ``fastLogin``,否則 fetch 回
    1004 ERR_ACC_NOT_LOGIN。token 來源(擇一):

    * env ``CN_ACCESS_TOKEN``;
    * 檔案 ``reviewer/tensoul-main/cn_access_token.txt``(第一行)。

    取得方式:瀏覽器登入 https://game.maj-soul.com/1 後,
    ``localStorage.getItem("access_token")`` 抄一顆(免密碼;一顆可複用、
    跨連線有效;失效時 prepareLogin 回 1002,再抄新的一顆即可)。
    """
    token = (
        os.environ.get("CN_ACCESS_TOKEN")
        or _read_cn_token_file()
    )
    if not token:
        raise RuntimeError(
            "CN server needs a browser access_token (prepareLogin{type:0}); "
            "create reviewer/tensoul-main/cn_access_token.txt containing the "
            "value of localStorage['access_token'] from "
            "https://game.maj-soul.com/1 (or set env CN_ACCESS_TOKEN)"
        )
    return {
        "MJS_BASE": "https://game.maj-soul.com/1",
        "MJS_RES": "0.11.252.w",
        "MJS_PKG": "4.0.46",
        "MJS_CVS": "WebGL_2022-4.0.46",
        "MJS_GATEWAY": "wss://route-2.maj-soul.com/gateway",
        # CN 服在國網直連即可;別讓打掛的 Clash 把 CN 抓譜堵死(JP 服才需要
        # 代理)。若你的網路連 CN 也要代理,設 env MJS_PROXY=http://... 覆寫。
        "MJS_PROXY": "direct",
        "CN_ACCESS_TOKEN": token,
    }


def _read_cn_token_file() -> str | None:
    try:
        raw = (TENSOUL_DIR / "cn_access_token.txt").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    token = raw.split()[0] if raw.split() else ""
    return token if len(token) > 10 else None


def is_mjsoul_url(value: str) -> bool:
    """True when the string looks like a Mahjong Soul share/replay link."""
    if not value:
        return False
    low = value.lower()
    if "paipu=" in low:
        return True
    return any(h in low for h in _MJSOUL_HOSTS)


# --------------------------------------------------------------------------- #
# local service auto-start (so `python review.py -u "<link>"` just works)
# --------------------------------------------------------------------------- #

TENSOUL_DIR = Path(__file__).resolve().parent / "tensoul-main"


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_local_service(
    service_url: str = DEFAULT_SERVICE_URL,
    *,
    env: dict | None = None,
    log_path: str | Path | None = None,
    print_fn: Callable[[str], None] = print,
    ready_timeout: float = 90.0,
) -> tuple[subprocess.Popen | None, bool]:
    """Make sure the local tensoul paipu service is reachable.

    * When `service_url` is not a localhost URL (a remote third-party service),
      nothing is started -> ``(None, False)``.
    * When something already listens on the port -> ``(None, False)``.
    * Otherwise it spawns ``node .`` inside `reviewer/tensoul-main` (with the
      given `env` overrides merged into the child environment, used for the CN
      server instance), waits until the port answers (or the process exits),
      and returns ``(proc, True)``. The caller should later call
      `stop_local_service(proc)` unless the service should stay up (e.g.
      batching many paipus).
    """
    url = (service_url or DEFAULT_SERVICE_URL).rstrip("/")
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 2563
    if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return None, False
    if _port_open(host, port):
        return None, False

    if not (TENSOUL_DIR / "index.js").is_file():
        raise RuntimeError(f"tensoul service not found: {TENSOUL_DIR} (node . entry missing)")

    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    else:
        log_file = subprocess.DEVNULL  # type: ignore[assignment]

    print_fn("local paipu service not running -> starting node . in "
             f"{TENSOUL_DIR.name}/ ...")
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    # The child service must listen on the SAME port we probe (a CN-instance
    # URL like :2564 differs from the node default 2563); respect an explicit
    # PORT when the caller already set one.
    child_env.setdefault("PORT", str(port))
    try:
        proc = subprocess.Popen(
            ["node", "."],
            cwd=str(TENSOUL_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=child_env,
        )
    except Exception as exc:
        if log_file is not subprocess.DEVNULL:
            log_file.close()
        raise RuntimeError(f"failed to start tensoul service (node): {exc}") from None

    deadline = time.monotonic() + max(1.0, ready_timeout)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            if log_file is not subprocess.DEVNULL:
                log_file.close()
            raise RuntimeError(
                f"tensoul service exited early (exit code {proc.returncode}); "
                f"check the log{(' at ' + str(log_path)) if log_path else ''}"
            )
        if _port_open(host, port, timeout=1.0):
            print_fn("local paipu service ready")
            return proc, True
        time.sleep(0.5)

    # never became ready
    try:
        proc.terminate()
    except Exception:
        pass
    if log_file is not subprocess.DEVNULL:
        log_file.close()
    raise RuntimeError(
        f"tensoul service did not become ready within {ready_timeout:.0f}s; "
        f"check the log{(' at ' + str(log_path)) if log_path else ''}"
    )


def stop_local_service(proc: subprocess.Popen | None) -> None:
    """Stop a service instance that `ensure_local_service` started."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    scheme: str = "Request",
    timeout: float = 20.0,
) -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"{scheme} {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            err = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(err, dict):
                detail = f" {err.get('code', '')} {err.get('message', '')}".rstrip()
            elif isinstance(payload, dict) and payload.get("detail"):
                detail = f" {payload['detail']}"
        except Exception:
            pass
        raise RuntimeError(f"paipu service HTTP {exc.code}{detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"cannot reach paipu service: {exc}") from None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paipu service returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("paipu service returned unexpected payload")
    return payload


def fetch_tenhou(
    share_url: str,
    out_path: str | Path,
    *,
    service_url: str = DEFAULT_SERVICE_URL,
    max_wait_seconds: float = 900.0,
    status_callback: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], Path]:
    """Fetch + convert `share_url`, write Tenhou JSON to `out_path`.

    Returns ``(result_dict, path)``.
    """
    service_url = service_url.rstrip("/")
    deadline = clock() + max(1.0, float(max_wait_seconds))

    created = _request(
        f"{service_url}/api/v1/desktop/requests",
        method="POST",
        body={"share_url": share_url},
    )
    request_id = str(created.get("request_id") or "").strip()
    token = str(created.get("request_token") or "").strip()
    if not request_id or not token:
        raise RuntimeError("paipu service did not return a request id / token")

    payload = created
    while True:
        state = str(payload.get("status") or "").strip()
        if status_callback:
            status_callback(state)
        if state == "ready":
            break
        if state in TERMINAL_BAD:
            err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            detail = " ".join(str(x) for x in (err.get("code"), err.get("message")) if x)
            raise RuntimeError(f"paipu fetch {state}: {detail or 'unknown error'}")
        if state not in PENDING_STATES:
            raise RuntimeError(f"paipu service returned unknown status: {state!r}")

        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError("timed out waiting for the paipu service")
        try:
            poll_ms = int(payload.get("poll_after_ms") or 1000)
        except (TypeError, ValueError):
            poll_ms = 1000
        delay = min(max(poll_ms / 1000.0, 0.25), 5.0)
        sleep(min(delay, remaining))

        rid = urllib.parse.quote(request_id, safe="")
        payload = _request(f"{service_url}/api/v1/requests/{rid}", token=token)

    rid = urllib.parse.quote(request_id, safe="")
    result = _request(
        f"{service_url}/api/v1/requests/{rid}/result",
        token=token,
        timeout=60.0,
    )

    if not isinstance(result.get("name"), list) or not isinstance(result.get("log"), list):
        raise RuntimeError("paipu service result is missing 'name' or 'log'")
    if "ver" not in result:
        raise RuntimeError("paipu service result is missing 'ver'")

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return result, path
