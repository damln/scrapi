"""
One-shot StealthyFetcher subprocess entry point.

Why this exists: camoufox browsers spawned by Scrapling can't be killed from
inside a ThreadPoolExecutor. When `asyncio.wait_for` cancels the Future, the
underlying C/subprocess work keeps running and leaks memory. Running the
fetch in a subprocess and SIGKILL'ing its process group on timeout is the
only reliable cleanup path.

CLI:
    python -m app.fetcher_worker <url> [--scroll-full]

Stdout on success:
    {"html": "...", "http_metadata": {...}}
Stderr + non-zero exit on failure.
"""

import argparse
import json
import sys

from scrapling.fetchers import StealthyFetcher

from app.config import PROXY_URL, SCRAPLING_TIMEOUT_MS
from app.cookie_dismiss import dismiss_cookies

SCROLL_STEP_PX = 800
SCROLL_DELAY_MS = 400
SCROLL_MAX_ITERATIONS = 40
SCROLL_SETTLE_MS = 1500


def _scroll_full_page(page):
    """Scroll the full page incrementally to trigger lazy-loaded content."""
    prev_height = page.evaluate("document.body.scrollHeight")

    for _ in range(SCROLL_MAX_ITERATIONS):
        current_pos = page.evaluate("window.pageYOffset")
        page.evaluate(f"window.scrollTo(0, {current_pos + SCROLL_STEP_PX})")
        page.wait_for_timeout(SCROLL_DELAY_MS)

        new_height = page.evaluate("document.body.scrollHeight")
        reached_bottom = page.evaluate(
            "window.pageYOffset + window.innerHeight >= document.body.scrollHeight - 50"
        )
        if reached_bottom and new_height == prev_height:
            break
        prev_height = new_height

    page.wait_for_timeout(SCROLL_SETTLE_MS)
    page.evaluate("window.scrollTo(0, 0)")
    return page


def _dismiss_cookies_and_scroll(page):
    page = dismiss_cookies(page)
    page = _scroll_full_page(page)
    return page


def _extract_http_metadata(page) -> dict:
    """Extract HTTP status, headers, and redirect history from a Scrapling Response."""
    history = []
    for entry in getattr(page, "history", []) or []:
        h = {"status": getattr(entry, "status", None), "url": getattr(entry, "url", None)}
        entry_headers = getattr(entry, "headers", None)
        if entry_headers:
            h["headers"] = dict(entry_headers)
        history.append(h)

    headers = getattr(page, "headers", None)
    return {
        "status": getattr(page, "status", None),
        "headers": dict(headers) if headers else None,
        "redirect_history": history if history else None,
    }


def fetch(url: str, scroll_full: bool) -> dict:
    action = _dismiss_cookies_and_scroll if scroll_full else dismiss_cookies
    fetch_kwargs = dict(
        headless=True,
        network_idle=True,
        timeout=SCRAPLING_TIMEOUT_MS,
        page_action=action,
        disable_ads=True,
    )
    if PROXY_URL:
        fetch_kwargs["proxy"] = PROXY_URL

    page = StealthyFetcher.fetch(url, **fetch_kwargs)
    html = page.body if isinstance(page.body, str) else page.body.decode("utf-8", errors="replace")
    http_metadata = _extract_http_metadata(page)
    return {"html": html, "http_metadata": http_metadata}


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot StealthyFetcher subprocess")
    parser.add_argument("url")
    parser.add_argument("--scroll-full", action="store_true")
    args = parser.parse_args()

    try:
        result = fetch(args.url, args.scroll_full)
    except Exception as exc:  # noqa: BLE001 — parent wraps this as a generic fetch failure
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1

    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
