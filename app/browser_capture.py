"""Supervised browser-capture orchestration for Scrapi's CLI.

Each attempt runs in a fresh process group so timeouts and cancellation kill
CloakBrowser plus every Chromium helper. Browser behavior lives in
``app.browser_capture_worker`` and reuses Scrapi's blockers and cookie filters.
"""

from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.worker_process import run_worker_process

CookieMode = Literal["dismiss", "keep"]
ScreenshotMode = Literal["full", "viewport", "off"]
ResourceMode = Literal["none", "media", "assets", "all"]


class BrowserCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserCaptureRequest:
    url: str
    output_dir: str
    width: int = 1440
    height: int = 1000
    headed: bool = False
    proxy_url: str = ""
    geoip: bool = False
    humanize: bool = True
    human_preset: str = "default"
    wait_until: str = "auto"
    wait_for_selector: str | None = None
    navigation_timeout_ms: int = 30_000
    networkidle_timeout_ms: int = 10_000
    hard_timeout_seconds: int = 90
    retries: int = 2
    cookie_mode: CookieMode = "dismiss"
    adblock: bool = True
    scroll_full: bool = False
    max_scroll_steps: int = 60
    screenshot: ScreenshotMode = "full"
    html: bool = True
    har: bool = True
    video: bool = False
    resources: ResourceMode = "none"
    max_resource_bytes: int = 20 * 1024 * 1024
    max_total_resource_bytes: int = 100 * 1024 * 1024


class BrowserCaptureApiRequest(BaseModel):
    """Stateless HTTP/CLI options; the server owns the temporary output path."""

    url: str
    width: int = Field(1440, ge=320, le=7680)
    height: int = Field(1000, ge=240, le=7680)
    headed: bool = False
    proxy_profile: str = "current"
    geoip: bool = False
    humanize: bool = True
    human_preset: Literal["default", "careful"] = "default"
    wait_until: Literal["auto", "load", "domcontentloaded", "networkidle", "commit"] = "auto"
    wait_for_selector: str | None = None
    navigation_timeout_ms: int = Field(30_000, ge=1_000, le=180_000)
    networkidle_timeout_ms: int = Field(10_000, ge=500, le=60_000)
    hard_timeout_seconds: int = Field(90, ge=5, le=600)
    retries: int = Field(2, ge=0, le=5)
    cookie_mode: CookieMode = "dismiss"
    adblock: bool = True
    scroll_full: bool = False
    max_scroll_steps: int = Field(60, ge=1, le=500)
    screenshot: ScreenshotMode = "full"
    html: bool = True
    har: bool = True
    video: bool = False
    resources: ResourceMode = "none"
    max_resource_bytes: int = Field(20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    max_total_resource_bytes: int = Field(100 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)

    model_config = {"extra": "forbid"}

    @field_validator("url")
    @classmethod
    def absolute_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute HTTP(S) URL")
        return value

    def to_capture_request(self, output_dir: str, proxy_url: str) -> BrowserCaptureRequest:
        payload = self.model_dump(exclude={"proxy_profile"})
        return BrowserCaptureRequest(output_dir=output_dir, proxy_url=proxy_url, **payload)


def _relative_artifact(path: str, evidence_dir: Path) -> str:
    return Path(path).resolve().relative_to(evidence_dir.resolve()).as_posix()


def build_capture_archive(result: dict[str, Any], evidence_dir: Path, archive_path: Path) -> dict[str, Any]:
    """Write a portable ZIP and return the result with relative artifact paths."""
    portable = copy.deepcopy(result)
    files = portable.get("files") or {}
    for key, value in files.items():
        if value:
            files[key] = _relative_artifact(value, evidence_dir)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("result.json", json.dumps(portable, indent=2))
        for path in sorted(item for item in evidence_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(evidence_dir).as_posix()
            if relative == "resources/manifest.json":
                manifest = json.loads(path.read_text())
                for entry in manifest.get("resources", []):
                    if entry.get("path"):
                        entry["path"] = _relative_artifact(entry["path"], evidence_dir)
                archive.writestr(relative, json.dumps(manifest, indent=2))
            else:
                archive.write(path, relative)
    return portable


async def capture_browser(request: BrowserCaptureRequest) -> dict[str, Any]:
    attempts = max(1, request.retries + 1)
    last_error = "capture failed"
    payload = json.dumps(asdict(request)).encode()

    for attempt in range(1, attempts + 1):
        try:
            process_result = await run_worker_process(
                "app.browser_capture_worker",
                input_bytes=payload,
                timeout_seconds=request.hard_timeout_seconds,
            )
        except TimeoutError:
            last_error = f"attempt {attempt} exceeded {request.hard_timeout_seconds}s"
            continue

        stderr_text = process_result.stderr.decode(errors="replace").strip()
        try:
            result = json.loads(process_result.stdout.decode(errors="replace"))
        except json.JSONDecodeError:
            result = {"status": "error", "error": stderr_text or "worker returned invalid JSON"}

        if process_result.returncode == 0 and result.get("status") == "success":
            result["attempt"] = attempt
            result["attempts_allowed"] = attempts
            return cast(dict[str, Any], result)
        last_error = result.get("error") or stderr_text or f"worker exit {process_result.returncode}"

    raise BrowserCaptureError(f"capture failed after {attempts} attempt(s): {last_error}")
