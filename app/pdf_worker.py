from __future__ import annotations

import base64
import json
import logging
import sys
from typing import Any
from urllib.parse import urlparse

from cloakbrowser import launch
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.ad_blocker import is_blocked
from app.config import PROXY_URL

logger = logging.getLogger(__name__)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_label(request: dict[str, Any]) -> str:
    return request.get("url") or "raw HTML"


def _pdf_options(page_options: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "margin": page_options["margin"],
        "scale": page_options["scale"],
        "print_background": page_options["print_background"],
        "prefer_css_page_size": page_options["prefer_css_page_size"],
        "landscape": page_options["landscape"],
        "display_header_footer": page_options["display_header_footer"],
        "outline": page_options["outline"],
        "tagged": page_options["tagged"],
    }
    for key in ("format", "width", "height", "page_ranges", "header_template", "footer_template"):
        value = page_options.get(key)
        if value is not None:
            options[key] = value
    return options


def _png_options(png_options: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "png",
        "full_page": png_options["full_page"],
        "omit_background": png_options["omit_background"],
        "scale": png_options["scale"],
    }


def _context_options(request: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "viewport": request["viewport"],
    }
    auth = request.get("basic_auth")
    if auth:
        credentials = {
            "username": auth["username"],
            "password": auth["password"],
            "origin": auth.get("origin") or _origin(request["url"]),
            "send": auth["send"],
        }
        options["http_credentials"] = credentials
    return options


def _route_handler(request: dict[str, Any]):
    headers = request.get("headers") or {}
    header_scope = request.get("header_scope") or "same_origin"
    target_origin = _origin(request["url"]) if request.get("url") else None

    def handle(route) -> None:
        route_url = route.request.url
        if is_blocked(route_url):
            route.abort()
            return

        should_add_headers = bool(headers) and (
            header_scope == "all" or (target_origin is not None and _origin(route_url) == target_origin)
        )
        if should_add_headers:
            route.continue_(headers={**route.request.headers, **headers})
        else:
            route.continue_()

    return handle


def _wait_for_readiness(page, request: dict[str, Any]) -> None:
    wait = request["wait"]
    timeout_ms = wait["timeout_ms"]

    if wait["network_idle"] and wait["goto"] != "networkidle":
        try:
            page.wait_for_load_state("networkidle", timeout=wait["network_idle_timeout_ms"])
        except Exception as exc:
            logger.debug("networkidle not reached for %s: %s", _request_label(request), exc)

    if wait["fonts"]:
        try:
            page.wait_for_function("() => !document.fonts || document.fonts.status === 'loaded'", timeout=timeout_ms)
        except Exception as exc:
            logger.debug("fonts not ready for %s: %s", _request_label(request), exc)

    if wait["selector"]:
        try:
            page.wait_for_selector(wait["selector"], timeout=wait["selector_timeout_ms"] or timeout_ms)
        except PlaywrightTimeoutError:
            if wait["selector_required"]:
                raise
            logger.debug("selector not found for %s: %s", _request_label(request), wait["selector"])

    if wait["ready_expression"]:
        try:
            page.wait_for_function(
                wait["ready_expression"],
                timeout=wait["ready_expression_timeout_ms"] or timeout_ms,
            )
        except PlaywrightTimeoutError:
            if wait["ready_expression_required"]:
                raise
            logger.debug("ready_expression not satisfied for %s", _request_label(request))


def _scroll_to_end(page, wait: dict[str, Any]) -> None:
    page.evaluate(
        """
        ({ stepPx, delayMs, maxSteps }) => new Promise(resolve => {
          let steps = 0;
          let stableBottomHits = 0;

          const height = () => Math.max(
            document.body ? document.body.scrollHeight : 0,
            document.documentElement ? document.documentElement.scrollHeight : 0
          );

          const tick = () => {
            const before = height();
            window.scrollBy(0, stepPx);
            const after = height();
            const atBottom = window.scrollY + window.innerHeight >= after - 2;

            if (atBottom && after === before) {
              stableBottomHits += 1;
            } else {
              stableBottomHits = 0;
            }

            steps += 1;
            if (stableBottomHits >= 3 || steps >= maxSteps) {
              resolve();
              return;
            }

            setTimeout(tick, delayMs);
          };

          tick();
        })
        """,
        {
            "stepPx": wait["scroll_step_px"],
            "delayMs": wait["scroll_delay_ms"],
            "maxSteps": wait["max_scroll_steps"],
        },
    )
    if wait["scroll_settle_ms"]:
        page.wait_for_timeout(wait["scroll_settle_ms"])


def _remove_elements(page, remove: dict[str, Any]) -> None:
    css_selectors = remove.get("css") or []
    xpath_selectors = remove.get("xpath") or []

    if css_selectors:
        page.evaluate(
            """
            selectors => {
              for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                  element.remove();
                }
              }
            }
            """,
            css_selectors,
        )

    if xpath_selectors:
        page.evaluate(
            """
            selectors => {
              for (const selector of selectors) {
                const snapshot = document.evaluate(
                  selector,
                  document,
                  null,
                  XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                  null
                );
                for (let i = 0; i < snapshot.snapshotLength; i += 1) {
                  const element = snapshot.snapshotItem(i);
                  if (element && element.remove) {
                    element.remove();
                  }
                }
              }
            }
            """,
            xpath_selectors,
        )


def _write_raw_html(page, request: dict[str, Any]) -> None:
    page.goto(
        "about:blank",
        wait_until="domcontentloaded",
        timeout=request["wait"]["timeout_ms"],
    )
    page.evaluate(
        """
        html => {
          document.open();
          document.write(html);
          document.close();
        }
        """,
        request["html"],
    )

    wait_until = request["wait"]["goto"]
    if wait_until != "commit":
        page.wait_for_load_state(wait_until, timeout=request["wait"]["timeout_ms"])


def render(request: dict[str, Any]) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {"humanize": True}
    if PROXY_URL:
        launch_kwargs["proxy"] = PROXY_URL

    browser = launch(**launch_kwargs)
    try:
        context = browser.new_context(**_context_options(request))
        page = context.new_page()
        page.route("**/*", _route_handler(request))

        if request.get("html") is not None:
            _write_raw_html(page, request)
            http_status = None
        else:
            response = page.goto(
                request["url"],
                wait_until=request["wait"]["goto"],
                timeout=request["wait"]["timeout_ms"],
            )
            http_status = response.status if response else None
            if http_status and http_status >= 400 and not request.get("render_http_errors"):
                return {
                    "status": "error",
                    "status_code": 502,
                    "error": f"Target returned HTTP {http_status}",
                    "http_status": http_status,
                    "final_url": page.url,
                }

        _wait_for_readiness(page, request)
        if request["wait"]["scroll_to_end"]:
            _scroll_to_end(page, request["wait"])
        _remove_elements(page, request["remove"])
        page.emulate_media(media=request["media"])

        if request["type"] == "png":
            data = page.screenshot(**_png_options(request["png"]))
            content_type = "image/png"
            extension = "png"
        else:
            data = page.pdf(**_pdf_options(request["page"]))
            content_type = "application/pdf"
            extension = "pdf"

        return {
            "status": "success",
            "data_base64": base64.b64encode(data).decode("ascii"),
            "content_type": content_type,
            "extension": extension,
            "http_status": http_status,
            "final_url": page.url,
        }
    finally:
        browser.close()


def main() -> int:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    try:
        result = render(request)
    except PlaywrightTimeoutError as exc:
        result = {
            "status": "error",
            "status_code": 504,
            "error": _compact_error(exc),
        }
    except Exception as exc:
        result = {
            "status": "error",
            "status_code": 502,
            "error": _compact_error(exc),
        }
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


def _compact_error(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else exc.__class__.__name__


if __name__ == "__main__":
    sys.exit(main())
