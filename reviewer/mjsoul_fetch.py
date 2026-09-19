#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch a Mahjong Soul (雀魂) paipu by share URL and convert it to Tenhou JSON.

Uses the public **anonymous desktop API** of <https://ninklang.tech>, so no
Mahjong Soul account is required:

    POST  {service}/api/v1/desktop/requests          {"share_url": <url>}
      ->  {request_id, request_token, status, poll_after_ms}
    GET   {service}/api/v1/requests/{id}             Authorization: Request <token>
      ->  {status: queued|fetching|converting|ready|failed|expired}
    GET   {service}/api/v1/requests/{id}/result      Authorization: Request <token>
      ->  Tenhou JSON: {ver, name, log, _target_actor?}

The result is the same "tenhou.net/6-ish" JSON that `mjai-reviewer -i` accepts,
and `_target_actor` (when present) is the seat decoded from the share link.

If you prefer not to use a third-party service, the local `tensoul` route
(Mahjong Soul account + password) can be used instead.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_SERVICE_URL = "https://ninklang.tech"
USER_AGENT = "Mortal-paipu-analyzer/2.0"

PENDING_STATES = {"queued", "fetching", "retry_wait", "converting"}
TERMINAL_BAD = {"failed", "expired"}

_MJSOUL_HOSTS = ("maj-soul.com", "mahjongsoul", "mahjong-soul", "majsoul")


def is_mjsoul_url(value: str) -> bool:
    """True when the string looks like a Mahjong Soul share/replay link."""
    if not value:
        return False
    low = value.lower()
    if "paipu=" in low:
        return True
    return any(h in low for h in _MJSOUL_HOSTS)


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
