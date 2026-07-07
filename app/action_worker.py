"""One-shot CloakBrowser subprocess that performs an authenticated action.

Mirror of ``app.pdf_worker`` (subprocess for cancellation + crash isolation),
but instead of rendering it:

1. opens a fresh stealth context with the session's UA / viewport / locale,
2. injects the session cookies via ``context.add_cookies`` so the page is
   already logged in,
3. optionally uploads media files through the real file input (something the
   XActions console scripts can't do),
4. runs a platform recipe (see ``app/recipes/``) or a raw browser script.

Platform-specific DOM logic lives in ``app/recipes/`` (one module per
platform); this worker stays platform-agnostic and only dispatches.

stdin  = single-line JSON request (cookies come inline from the caller's
         request; media paths are resolved by the async runner).
stdout = single-line JSON result. Exit 0 always; errors are in the payload.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from typing import Any

from cloakbrowser import launch
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.config import PROXY_URL
from app.recipes import RECIPES, helpers

logger = logging.getLogger(__name__)


def _context_options(req: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if req.get("viewport"):
        options["viewport"] = req["viewport"]
    if req.get("user_agent"):
        options["user_agent"] = req["user_agent"]
    if req.get("locale"):
        options["locale"] = req["locale"]
    if req.get("timezone"):
        options["timezone_id"] = req["timezone"]
    if req.get("extra_headers"):
        options["extra_http_headers"] = req["extra_headers"]
    return options


def run(req: dict[str, Any]) -> dict[str, Any]:
    timeout = req["timeout_ms"]
    launch_kwargs: dict[str, Any] = {"humanize": True}
    if PROXY_URL:
        launch_kwargs["proxy"] = PROXY_URL

    browser = launch(**launch_kwargs)
    try:
        context = browser.new_context(**_context_options(req))
        context.add_cookies(req["cookies"])
        page = context.new_page()
        page.goto(req["url"], wait_until="domcontentloaded", timeout=timeout)

        log: list[str] = []
        recipe = req.get("recipe")
        if recipe:
            recipe_fn = RECIPES.get(recipe)
            if recipe_fn is None:
                return {"status": "error", "status_code": 400, "error": f"unknown recipe: {recipe}"}
            result = recipe_fn(page, req, log)
        else:
            # Raw-script escape hatch: platform unknown, so any media goes
            # through a generic file input and the script runs in the page.
            helpers.upload_media(page, req.get("media_paths") or [], helpers.ANY_FILE_INPUT, None, timeout, log)
            result = page.evaluate(req["script"], req.get("params"))

        screenshot_b64 = None
        if req.get("screenshot"):
            screenshot_b64 = base64.b64encode(page.screenshot()).decode("ascii")

        return {
            "status": "success",
            "result": result,
            "log": log,
            "final_url": page.url,
            "screenshot_base64": screenshot_b64,
        }
    finally:
        browser.close()


def _compact_error(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else exc.__class__.__name__


def main() -> int:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    try:
        result = run(req)
    except PlaywrightTimeoutError as exc:
        result = {"status": "error", "status_code": 504, "error": _compact_error(exc)}
    except Exception as exc:  # surface any browser error as JSON, never crash the worker
        result = {"status": "error", "status_code": 502, "error": _compact_error(exc)}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
