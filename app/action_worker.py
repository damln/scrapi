"""One-shot CloakBrowser subprocess that performs an authenticated action.

Platform-specific DOM logic lives in ``app/recipes/``; this worker only
dispatches.

stdin  = single-line JSON request.
stdout = single-line JSON result. Exit 0 always; errors are in the payload.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.browser_worker import compact_error, launch_cloak_browser
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
    browser = launch_cloak_browser()
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


def main() -> int:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    try:
        result = run(req)
    except PlaywrightTimeoutError as exc:
        result = {"status": "error", "status_code": 504, "error": compact_error(exc)}
    except Exception as exc:
        result = {"status": "error", "status_code": 502, "error": compact_error(exc)}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
