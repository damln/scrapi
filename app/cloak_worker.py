"""CloakBrowser subprocess entry point for persistent and one-shot fetching.

stdout = single-line JSON result; stderr = logs / tracebacks. Exit 0
on success, non-zero on any error.

Why a subprocess (not in-process from the FastAPI worker):
- Reliable cancellation: SIGKILL the process group from `cloak_fetcher`
  on asyncio timeout / cancel, and every Chromium helper dies with it.
- Crash isolation: a hung browser can't take out the API process.
- No event-loop interleaving — `launch()` is the sync API, simpler.

Server mode keeps Chromium alive across requests. Every request still creates
and closes an isolated browser context, so cookies and storage are not shared.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from cloakbrowser import launch

from app.ad_blocker import block_ads
from app.config import FETCH_TIMEOUT_MS, PROXY_URL
from app.cookie_dismiss import dismiss_cookies

logger = logging.getLogger(__name__)


def _scroll_full_script() -> str:
    """JS: incremental scroll to the bottom in 500px steps, 100ms apart.

    Incremental scroll to trigger lazy-load on long pages.
    """
    return (
        "() => new Promise(resolve => {"
        "  let total = 0;"
        "  const step = 500;"
        "  const i = setInterval(() => {"
        "    window.scrollBy(0, step);"
        "    total += step;"
        "    if (total >= document.body.scrollHeight) {"
        "      clearInterval(i);"
        "      resolve();"
        "    }"
        "  }, 100);"
        "})"
    )


def _launch_browser():
    launch_kwargs: dict[str, Any] = {"humanize": True}
    if PROXY_URL:
        launch_kwargs["proxy"] = PROXY_URL
    return launch(**launch_kwargs)


def fetch(
    browser,
    url: str,
    scroll_full: bool,
    wait_until: str | None,
    wait_for_selector: str | None,
) -> dict:
    context = browser.new_context()
    try:
        page = context.new_page()
        # Network-layer ad/tracker blocking — must register BEFORE goto so
        # requests fired during page load can be aborted.
        page.route("**/*", block_ads)
        # Two-stage wait: goto until `load`, then OPTIONALLY wait for
        # `networkidle` with a tight cap. Sites with long-poll / WebSocket
        # activity (Discourse, dashboards) never reach networkidle and
        # would otherwise time out the whole fetch. Splitting lets us get
        # the load-state HTML in those cases and only pay the networkidle
        # tax when the page can actually settle. On well-behaved pages
        # load fires fast and networkidle follows in ~1s — same total
        # time as a single networkidle goto.
        goto_wait = wait_until or "load"
        response = page.goto(url, timeout=FETCH_TIMEOUT_MS, wait_until=goto_wait)
        if wait_until is None:
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception as exc:
                logger.debug("networkidle not reached for %s in 10s: %s", url, exc)
        # Cookie banner dismissal. Best-effort: any exception (banner not
        # present, JS error, timeout) is logged but the fetch continues;
        # we still return the HTML we have.
        try:
            dismiss_cookies(page)
        except Exception as exc:
            logger.debug("dismiss_cookies failed for %s: %s", url, exc)
        if wait_for_selector:
            page.wait_for_selector(wait_for_selector, timeout=FETCH_TIMEOUT_MS)
        if scroll_full:
            page.evaluate(_scroll_full_script())
        html = page.content()
        status = response.status if response else None
        return {
            "html": html,
            "http_metadata": {"status": status, "redirect_history": None},
        }
    finally:
        context.close()


def _write_protocol(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _compact_error(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else exc.__class__.__name__


def serve() -> int:
    try:
        browser = _launch_browser()
    except Exception as exc:
        _write_protocol({"ok": False, "error": _compact_error(exc)})
        return 1
    try:
        for raw_request in sys.stdin:
            try:
                request = json.loads(raw_request)
                result = fetch(
                    browser,
                    request["url"],
                    bool(request.get("scroll_full")),
                    request.get("wait_until"),
                    request.get("wait_for_selector"),
                )
            except Exception as exc:
                _write_protocol({"ok": False, "error": _compact_error(exc)})
                return 1
            _write_protocol({"ok": True, "result": result})
        return 0
    finally:
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot CloakBrowser subprocess")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--scroll-full", action="store_true")
    parser.add_argument("--wait-until")
    parser.add_argument("--wait-for-selector")
    args = parser.parse_args()

    if args.serve:
        return serve()
    if args.url is None:
        parser.error("url is required unless --serve is used")

    browser = _launch_browser()
    try:
        result = fetch(browser, args.url, args.scroll_full, args.wait_until, args.wait_for_selector)
    finally:
        browser.close()
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
