"""CloakBrowser provider — primary entry in the default fallback chain.

CloakBrowser is a stealth Chromium with C++-level fingerprint patches
(canvas, WebGL, audio, fonts, WebRTC, automation signals) and native
SOCKS5 support.
PyPI: `cloakbrowser`. Docs: https://github.com/CloakHQ/CloakBrowser

Runs through a bounded pool of persistent, killable `app.cloak_worker`
subprocesses. Chromium is reused, while every URL gets a fresh context.
"""

from __future__ import annotations

from app.cloak_pool import CloakBrowserPool
from app.config import BROWSER_MAX_CONCURRENT, BROWSER_MAX_REQUESTS_PER_WORKER

_browser_pool: CloakBrowserPool | None = None


def init_browser_pool() -> None:
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = CloakBrowserPool(BROWSER_MAX_CONCURRENT, BROWSER_MAX_REQUESTS_PER_WORKER)


async def close_browser_pool() -> None:
    global _browser_pool
    pool = _browser_pool
    _browser_pool = None
    if pool is not None:
        await pool.close()


def _get_browser_pool() -> CloakBrowserPool:
    init_browser_pool()
    if _browser_pool is None:
        raise RuntimeError("cloak browser pool failed to initialize")
    return _browser_pool


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
    payload = {
        "url": url,
        "scroll_full": scroll_full,
        "wait_until": wait_until,
        "wait_for_selector": wait_for_selector,
    }
    result = await _get_browser_pool().execute(payload, proxy_url or "")
    return result["html"], result.get("http_metadata") or {}
