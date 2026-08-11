"""CloakBrowser provider — primary entry in the default fallback chain.

CloakBrowser is a stealth Chromium with C++-level fingerprint patches
(canvas, WebGL, audio, fonts, WebRTC, automation signals) and native
SOCKS5 support.
PyPI: `cloakbrowser`. Docs: https://github.com/CloakHQ/CloakBrowser

Runs as a killable subprocess via `app.cloak_worker` so asyncio
cancellation reliably kills the underlying Chrome process group.
"""

from __future__ import annotations

import json
import os

from app.worker_process import run_worker_process


async def fetch_with_cloak(
    url: str,
    scroll_full: bool = False,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
    proxy_url: str | None = None,
) -> tuple[str, dict]:
    """Fetch using CloakBrowser inside a killable subprocess.

    Returns `(html, http_metadata)`. `http_metadata` carries
    `{"status": int|None, "redirect_history": None}`.
    """
    args = [url]
    if scroll_full:
        args.append("--scroll-full")
    if wait_until:
        args.extend(["--wait-until", wait_until])
    if wait_for_selector:
        args.extend(["--wait-for-selector", wait_for_selector])

    env = os.environ.copy()
    if proxy_url is not None:
        env["PROXY_URL"] = proxy_url

    result = await run_worker_process("app.cloak_worker", *args, env=env)

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cloak_worker exit {result.returncode}: {err[:500]}")

    payload = json.loads(result.stdout.decode("utf-8", errors="replace"))
    return payload["html"], payload.get("http_metadata") or {}
