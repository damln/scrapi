"""One-shot CloakBrowser worker for screenshots, video, HAR, DOM, and resources."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from cloakbrowser import launch
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.ad_blocker import block_ads
from app.cookie_dismiss import dismiss_cookies

logger = logging.getLogger(__name__)

RESOURCE_TYPES = {
    "none": frozenset(),
    "media": frozenset({"image", "media"}),
    "assets": frozenset({"image", "media", "font", "stylesheet"}),
    "all": frozenset({"image", "media", "font", "stylesheet", "script", "xhr", "fetch"}),
}


def _safe_name(url: str, index: int) -> str:
    parsed = urlparse(url)
    original = Path(unquote(parsed.path)).name or f"resource-{index}"
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", original).strip(".-") or f"resource-{index}"
    stem = Path(clean).stem[:80] or f"resource-{index}"
    suffix = Path(clean).suffix[:16]
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"{stem}-{digest}{suffix}"


class ResourceCollector:
    def __init__(self, output_dir: Path, mode: str, per_file: int, total: int):
        self.output_dir = output_dir
        self.allowed = RESOURCE_TYPES[mode]
        self.per_file = per_file
        self.total_limit = total
        self.total = 0
        self.entries: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        if self.allowed:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def handle(self, response: Any) -> None:
        resource_type = response.request.resource_type
        if resource_type not in self.allowed or response.url in self.seen:
            return
        self.seen.add(response.url)
        try:
            content_length = int(response.headers.get("content-length") or 0)
        except ValueError:
            content_length = 0
        if content_length > self.per_file or self.total + content_length > self.total_limit:
            self.entries.append({"url": response.url, "type": resource_type, "skipped": "size-cap"})
            return
        try:
            body = response.body()
        except Exception as exc:
            self.entries.append({"url": response.url, "type": resource_type, "skipped": str(exc)[:160]})
            return
        if len(body) > self.per_file or self.total + len(body) > self.total_limit:
            self.entries.append({"url": response.url, "type": resource_type, "skipped": "size-cap"})
            return
        path = self.output_dir / _safe_name(response.url, len(self.entries))
        path.write_bytes(body)
        self.total += len(body)
        self.entries.append(
            {
                "url": response.url,
                "status": response.status,
                "type": resource_type,
                "content_type": response.headers.get("content-type"),
                "bytes": len(body),
                "path": str(path),
            }
        )

    def write_manifest(self) -> str | None:
        if not self.allowed:
            return None
        path = self.output_dir / "manifest.json"
        path.write_text(json.dumps({"total_bytes": self.total, "resources": self.entries}, indent=2))
        return str(path)


def _scroll_full(page: Any, max_steps: int) -> dict[str, Any]:
    steps = 0
    stable = 0
    previous_height = 0
    while steps < max_steps:
        metrics = page.evaluate(
            "() => ({y: window.scrollY, h: document.documentElement.scrollHeight, v: window.innerHeight})"
        )
        at_end = metrics["y"] + metrics["v"] >= metrics["h"] - 4
        if at_end and metrics["h"] == previous_height:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        previous_height = metrics["h"]
        page.mouse.wheel(0, max(240, int(metrics["v"] * 0.72)))
        page.wait_for_timeout(220)
        steps += 1
    return {
        "steps": steps,
        "height": page.evaluate("() => document.documentElement.scrollHeight"),
        "capped": steps >= max_steps,
    }


def _capture_screenshot(page: Any, req: dict[str, Any], path: Path, width: int, height: int) -> dict[str, Any]:
    screenshot_format = req["screenshot_format"]
    render_scale = int(req.get("render_scale", 1))
    options: dict[str, Any] = {
        "animations": "disabled",
        "caret": "hide",
    }

    page.evaluate("() => window.scrollTo(0, 0)")
    page_height = int(
        page.evaluate("() => Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
    )
    if req["screenshot"] == "full":
        capture_height = min(page_height, int(req["max_screenshot_height"]))
        capped = page_height > capture_height
        if capped:
            options["clip"] = {"x": 0, "y": 0, "width": width, "height": capture_height}
        else:
            options["full_page"] = True
    else:
        capture_height = height
        capped = False
        options["full_page"] = False

    if render_scale == 1:
        options.update(path=str(path), type=screenshot_format, scale="css")
        if screenshot_format == "jpeg":
            options["quality"] = int(req["screenshot_quality"])
        page.screenshot(**options)
    else:
        # Capture losslessly at the browser's Retina density, then downsample once.
        # The caller still receives the exact CSS-pixel dimensions it requested.
        retina_path = path.with_name(f"{path.stem}.retina.png")
        try:
            options.update(path=str(retina_path), type="png", scale="device")
            page.screenshot(**options)
            with Image.open(retina_path) as retina:
                output = retina.resize((width, capture_height), Image.Resampling.LANCZOS)
                if screenshot_format == "jpeg":
                    output.convert("RGB").save(
                        path,
                        format="JPEG",
                        quality=int(req["screenshot_quality"]),
                        subsampling=0,
                        optimize=True,
                    )
                else:
                    output.save(path, format="PNG", optimize=True)
        finally:
            retina_path.unlink(missing_ok=True)

    return {
        "mode": req["screenshot"],
        "format": screenshot_format,
        "quality": int(req["screenshot_quality"]) if screenshot_format == "jpeg" else None,
        "width": width,
        "height": capture_height,
        "render_scale": render_scale,
        "page_height": page_height,
        "capped": capped,
    }


def run(req: dict[str, Any]) -> dict[str, Any]:
    output = Path(req["output_dir"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    width, height = int(req["width"]), int(req["height"])
    har_path = output / "capture.har"
    html_path = output / "page.html"
    screenshot_extension = "jpg" if req["screenshot_format"] == "jpeg" else "png"
    screenshot_path = output / f"screenshot.{screenshot_extension}"
    video_dir = output / ".video"
    video_path = output / "capture.webm"
    resources_dir = output / "resources"

    launch_kwargs: dict[str, Any] = {
        "headless": not req["headed"],
        "humanize": req["humanize"],
        "human_preset": req["human_preset"],
    }
    if req["proxy_url"]:
        launch_kwargs["proxy"] = req["proxy_url"]
        launch_kwargs["geoip"] = req["geoip"]

    context_kwargs: dict[str, Any] = {
        "viewport": {"width": width, "height": height},
        "device_scale_factor": int(req.get("render_scale", 1)),
    }
    if req["har"]:
        context_kwargs.update(record_har_path=str(har_path), record_har_mode="full")
    if req["video"]:
        video_dir.mkdir(parents=True, exist_ok=True)
        context_kwargs.update(record_video_dir=str(video_dir), record_video_size={"width": width, "height": height})

    collector = ResourceCollector(
        resources_dir,
        req["resources"],
        int(req["max_resource_bytes"]),
        int(req["max_total_resource_bytes"]),
    )
    browser = launch(**launch_kwargs)
    context = None
    page = None
    started = time.monotonic()
    result: dict[str, Any] | None = None
    try:
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(req["navigation_timeout_ms"])
        if req["adblock"]:
            page.route("**/*", block_ads)
        if collector.allowed:
            page.on("response", collector.handle)

        goto_wait = "load" if req["wait_until"] == "auto" else req["wait_until"]
        response = page.goto(req["url"], wait_until=goto_wait, timeout=req["navigation_timeout_ms"])
        networkidle = None
        if req["wait_until"] == "auto":
            try:
                page.wait_for_load_state("networkidle", timeout=req["networkidle_timeout_ms"])
                networkidle = True
            except PlaywrightTimeoutError:
                networkidle = False

        if req["cookie_mode"] == "dismiss":
            dismiss_cookies(page)
        if req["wait_for_selector"]:
            page.wait_for_selector(req["wait_for_selector"], timeout=req["navigation_timeout_ms"])

        scroll = _scroll_full(page, req["max_scroll_steps"]) if req["scroll_full"] else None
        if req["html"]:
            html_path.write_text(page.content())
        screenshot = None
        if req["screenshot"] != "off":
            screenshot = _capture_screenshot(page, req, screenshot_path, width, height)

        result = {
            "status": "success",
            "url": page.url,
            "title": page.title(),
            "http_status": response.status if response else None,
            "viewport": {"width": width, "height": height},
            "networkidle": networkidle,
            "cookie_banner": req["cookie_mode"],
            "scroll": scroll,
            "screenshot": screenshot,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        if req["video"] and page.video:
            video = page.video
            page.close()
            page = None
            video.save_as(str(video_path))
    finally:
        if page is not None:
            page.close()
        if context is not None:
            context.close()
        browser.close()
        if video_dir.is_dir():
            for child in video_dir.iterdir():
                child.unlink(missing_ok=True)
            video_dir.rmdir()

    if result is None:
        raise RuntimeError("capture ended without a result")
    resource_manifest = collector.write_manifest()
    result["files"] = {
        "html": str(html_path) if req["html"] else None,
        "har": str(har_path) if req["har"] else None,
        "screenshot": str(screenshot_path) if req["screenshot"] != "off" else None,
        "video": str(video_path) if req["video"] else None,
        "resource_manifest": resource_manifest,
    }
    result["resources"] = {"count": len(collector.entries), "bytes": collector.total}
    return result


def _compact_error(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else exc.__class__.__name__


def main() -> int:
    req = json.loads(sys.stdin.buffer.read())
    try:
        result = run(req)
        code = 0
    except Exception as exc:
        logger.exception("browser capture failed")
        result = {"status": "error", "error": _compact_error(exc)}
        code = 1
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
