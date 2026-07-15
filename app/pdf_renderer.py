from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import PDF_MAX_CONCURRENT, PDF_RENDER_TIMEOUT_MS

logger = logging.getLogger(__name__)

HeaderScope = Literal["same_origin", "all"]
MediaMode = Literal["screen", "print"]
GotoWaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]
BasicAuthSend = Literal["unauthorized", "always"]
ExportType = Literal["pdf", "png"]
PngScale = Literal["css", "device"]
RasterQuality = Literal["best", "optimized"]

PDF_FORMATS = {
    "Letter",
    "Legal",
    "Tabloid",
    "Ledger",
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
}

FORBIDDEN_HEADER_NAMES = {
    "connection",
    "content-length",
    "host",
    "proxy-authorization",
    "transfer-encoding",
}


class PdfRenderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class MarginOptions(BaseModel):
    top: str | float = "0"
    right: str | float = "0"
    bottom: str | float = "0"
    left: str | float = "0"

    @field_validator("top", "right", "bottom", "left")
    @classmethod
    def validate_margin(cls, value: str | float) -> str | float:
        return _validate_pdf_dimension(value)


class PdfPageOptions(BaseModel):
    width: str | float | None = "10in"
    height: str | float | None = "7.5in"
    format: str | None = None
    margin: MarginOptions = Field(default_factory=MarginOptions)
    scale: float = Field(1, ge=0.1, le=2)
    print_background: bool = True
    prefer_css_page_size: bool = False
    landscape: bool = False
    page_ranges: str | None = None
    display_header_footer: bool = False
    header_template: str | None = None
    footer_template: str | None = None
    outline: bool = False
    tagged: bool = False
    rasterize: bool = True
    raster_quality: RasterQuality = "best"

    @model_validator(mode="before")
    @classmethod
    def clear_default_dimensions_for_format(cls, data):
        if isinstance(data, dict) and data.get("format") and "width" not in data and "height" not in data:
            data = data.copy()
            data["width"] = None
            data["height"] = None
        return data

    @field_validator("width", "height")
    @classmethod
    def validate_dimension(cls, value: str | float | None) -> str | float | None:
        if value is None:
            return None
        return _validate_pdf_dimension(value)

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in PDF_FORMATS:
            valid = ", ".join(sorted(PDF_FORMATS))
            raise ValueError(f"format must be one of: {valid}")
        return value

    @model_validator(mode="after")
    def validate_size_strategy(self):
        if self.format and (self.width is not None or self.height is not None):
            raise ValueError("format cannot be combined with width or height")
        if not self.format and (self.width is None or self.height is None):
            raise ValueError("width and height are required when format is not set")
        return self


class PdfViewportOptions(BaseModel):
    width: int = Field(1600, ge=320, le=7680)
    height: int = Field(1200, ge=240, le=7680)


class PdfWaitOptions(BaseModel):
    goto: GotoWaitUntil = "load"
    network_idle: bool = True
    network_idle_timeout_ms: int = Field(10_000, ge=0, le=120_000)
    fonts: bool = True
    selector: str | None = None
    selector_required: bool = True
    selector_timeout_ms: int | None = Field(None, ge=1_000, le=120_000)
    ready_expression: str | None = None
    ready_expression_required: bool = True
    ready_expression_timeout_ms: int | None = Field(None, ge=1_000, le=120_000)
    scroll_to_end: bool = False
    scroll_step_px: int = Field(700, ge=100, le=5000)
    scroll_delay_ms: int = Field(100, ge=0, le=5000)
    scroll_settle_ms: int = Field(1000, ge=0, le=30000)
    max_scroll_steps: int = Field(200, ge=1, le=2000)
    timeout_ms: int = Field(30_000, ge=1_000, le=120_000)

    @field_validator("selector", "ready_expression")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class BasicAuthOptions(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    origin: str | None = None
    send: BasicAuthSend = "unauthorized"

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("origin must be an HTTP origin with scheme, host, and optional port")
        return f"{parsed.scheme}://{parsed.netloc}"


class PdfRemoveOptions(BaseModel):
    css: list[str] = Field(default_factory=list, max_length=100)
    xpath: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("css", "xpath")
    @classmethod
    def validate_selectors(cls, values: list[str]) -> list[str]:
        selectors = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("selectors cannot be blank")
            if len(value) > 1000:
                raise ValueError("selectors cannot exceed 1000 characters")
            selectors.append(value)
        return selectors


class PngOptions(BaseModel):
    full_page: bool = True
    omit_background: bool = False
    scale: PngScale = "device"


def _default_viewport_options() -> PdfViewportOptions:
    return PdfViewportOptions(width=1600, height=1200)


def _default_page_options() -> PdfPageOptions:
    return PdfPageOptions(
        width="10in",
        height="7.5in",
        format=None,
        margin=MarginOptions(top="0", right="0", bottom="0", left="0"),
        scale=1,
        print_background=True,
        prefer_css_page_size=False,
        landscape=False,
        page_ranges=None,
        display_header_footer=False,
        header_template=None,
        footer_template=None,
        outline=False,
        tagged=False,
        rasterize=True,
        raster_quality="best",
    )


def _default_wait_options() -> PdfWaitOptions:
    return PdfWaitOptions(
        goto="load",
        network_idle=True,
        network_idle_timeout_ms=10_000,
        fonts=True,
        selector=None,
        selector_required=True,
        selector_timeout_ms=None,
        ready_expression=None,
        ready_expression_required=True,
        ready_expression_timeout_ms=None,
        scroll_to_end=False,
        scroll_step_px=700,
        scroll_delay_ms=100,
        scroll_settle_ms=1000,
        max_scroll_steps=200,
        timeout_ms=30_000,
    )


def _default_remove_options() -> PdfRemoveOptions:
    return PdfRemoveOptions(css=[], xpath=[])


def _default_png_options() -> PngOptions:
    return PngOptions(full_page=True, omit_background=False, scale="device")


class PdfRenderRequest(BaseModel):
    url: str | None = Field(None, min_length=1)
    html: str | None = Field(None, min_length=1)
    type: ExportType = "pdf"
    headers: dict[str, str] = Field(default_factory=dict)
    header_scope: HeaderScope = "same_origin"
    basic_auth: BasicAuthOptions | None = None
    viewport: PdfViewportOptions = Field(default_factory=_default_viewport_options)
    media: MediaMode = "screen"
    page: PdfPageOptions = Field(default_factory=_default_page_options)
    png: PngOptions = Field(default_factory=_default_png_options)
    wait: PdfWaitOptions = Field(default_factory=_default_wait_options)
    remove: PdfRemoveOptions = Field(default_factory=_default_remove_options)
    render_http_errors: bool = False
    model_config = {"extra": "forbid"}

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http or https URL")
        return value

    @model_validator(mode="after")
    def validate_source(self):
        if bool(self.url) == bool(self.html):
            raise ValueError("exactly one of url or html is required")
        if self.html is not None and self.basic_auth is not None:
            raise ValueError("basic_auth requires url")
        if self.html is not None and self.headers:
            raise ValueError("headers require url")
        return self

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for name, header_value in value.items():
            normalized = name.strip().lower()
            if not normalized or normalized in FORBIDDEN_HEADER_NAMES:
                raise ValueError(f"header is not allowed: {name}")
            if any(char in name for char in "\r\n:") or any(char in header_value for char in "\r\n"):
                raise ValueError("headers cannot contain control characters")
        return value


@dataclass(frozen=True)
class PdfRenderResult:
    data: bytes
    content_type: str
    extension: str
    final_url: str | None
    http_status: int | None


_pdf_semaphore: asyncio.Semaphore | None = None


def _get_pdf_semaphore() -> asyncio.Semaphore:
    global _pdf_semaphore
    if _pdf_semaphore is None:
        _pdf_semaphore = asyncio.Semaphore(PDF_MAX_CONCURRENT)
    return _pdf_semaphore


def _validate_pdf_dimension(value: str | float) -> str | float:
    if isinstance(value, int | float):
        if value < 0:
            raise ValueError("dimension must be non-negative")
        return value

    stripped = value.strip()
    if stripped == "0":
        return stripped

    units = ("px", "in", "cm", "mm")
    if not stripped.endswith(units):
        raise ValueError("dimension must use px, in, cm, or mm")

    number = stripped[:-2]
    try:
        parsed = float(number)
    except ValueError as exc:
        raise ValueError("dimension must start with a number") from exc
    if parsed < 0:
        raise ValueError("dimension must be non-negative")
    return stripped


def _killpg(pid: int) -> None:
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


async def render_pdf(request: PdfRenderRequest) -> PdfRenderResult:
    return await render_export(request)


async def render_export(request: PdfRenderRequest) -> PdfRenderResult:
    sem = _get_pdf_semaphore()
    async with sem:
        return await _render_pdf_in_subprocess(request)


async def _render_pdf_in_subprocess(request: PdfRenderRequest) -> PdfRenderResult:
    payload = request.model_dump(mode="json")
    timeout_ms = max(PDF_RENDER_TIMEOUT_MS, request.wait.timeout_ms + 15_000)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.pdf_worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(payload).encode("utf-8")),
            timeout=timeout_ms / 1000,
        )
    except TimeoutError as exc:
        _killpg(proc.pid)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=3)
        raise PdfRenderError(f"Export render timeout ({timeout_ms}ms)", status_code=504) from exc
    except asyncio.CancelledError:
        _killpg(proc.pid)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=3)
        raise

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise PdfRenderError(f"pdf_worker exit {proc.returncode}: {stderr_text[:500]}")

    try:
        result = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise PdfRenderError("pdf_worker returned invalid JSON") from exc

    if result.get("status") != "success":
        status_code = int(result.get("status_code") or 502)
        error = result.get("error") or "Export render failed"
        raise PdfRenderError(error, status_code=status_code)

    return PdfRenderResult(
        data=base64.b64decode(result["data_base64"]),
        content_type=result["content_type"],
        extension=result["extension"],
        final_url=result.get("final_url"),
        http_status=result.get("http_status"),
    )
