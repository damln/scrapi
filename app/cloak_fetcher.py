"""CloakBrowser provider — primary entry in the default fallback chain.

CloakBrowser is a stealth Chromium with C++-level fingerprint patches
(canvas, WebGL, audio, fonts, WebRTC, automation signals) and native
SOCKS5 support.
PyPI: `cloakbrowser`. Docs: https://github.com/CloakHQ/CloakBrowser

Runs as a killable subprocess via `app.cloak_worker` so asyncio
cancellation reliably kills the underlying Chrome process group.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys

logger = logging.getLogger(__name__)


def _killpg(pid: int) -> None:
    """SIGKILL the process group for pid. Safe if the group is already gone."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning("killpg(%s) denied: %s", pgid, exc)


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
    cmd = [sys.executable, "-m", "app.cloak_worker", url]
    if scroll_full:
        cmd.append("--scroll-full")
    if wait_until:
        cmd.extend(["--wait-until", wait_until])
    if wait_for_selector:
        cmd.extend(["--wait-for-selector", wait_for_selector])

    # start_new_session=True puts the child in its own process group so
    # a single killpg reaches every Chromium helper it spawned.
    env = os.environ.copy()
    if proxy_url is not None:
        env["PROXY_URL"] = proxy_url

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )

    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        _killpg(proc.pid)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=3)
        raise

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cloak_worker exit {proc.returncode}: {err[:500]}")

    result = json.loads(stdout.decode("utf-8", errors="replace"))
    return result["html"], result.get("http_metadata") or {}
