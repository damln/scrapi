"""Async orchestration for the browser-action engine.

Inline and remote media are written to a temp dir here, so the worker
(``app.action_worker``) only ever sees file paths.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app import asset_fetcher
from app.browser_budget import browser_slot
from app.config import ACTION_MAX_CONCURRENT, ACTION_RENDER_TIMEOUT_MS
from app.worker_process import WorkerError, run_json_worker

SameSite = Literal["Strict", "Lax", "None"]

_EXT_BY_CT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "image/svg+xml": ".svg",
}


class ActionError(WorkerError):
    pass


class Cookie(BaseModel):
    """A single cookie in Playwright ``add_cookies`` shape.

    Accepts the camelCase keys Playwright/Chrome use (``httpOnly``,
    ``sameSite``) and re-emits them via ``by_alias`` dumping.
    """

    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = None
    http_only: bool = Field(False, alias="httpOnly")
    secure: bool = False
    same_site: SameSite | None = Field(None, alias="sameSite")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    def to_playwright(self) -> dict:
        """Playwright-ready dict: camelCase keys, no null fields."""
        return self.model_dump(by_alias=True, exclude_none=True)


class Viewport(BaseModel):
    width: int = Field(..., ge=320, le=7680)
    height: int = Field(..., ge=240, le=7680)


class Session(BaseModel):
    """Browser identity passed inline by the caller — cookies plus the UA /
    viewport / locale they were captured with.

    The worker replays this into a fresh CloakBrowser context so the page
    lands already logged in. The API is stateless: this is supplied on every
    request and never persisted server-side.
    """

    cookies: list[Cookie] = Field(..., min_length=1)
    user_agent: str | None = None
    viewport: Viewport | None = None
    locale: str | None = None
    timezone: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


class MediaItem(BaseModel):
    data_base64: str | None = None
    url: str | None = None
    filename: str | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def exactly_one_source(self) -> MediaItem:
        if bool(self.data_base64) == bool(self.url):
            raise ValueError("each media item needs exactly one of data_base64 or url")
        if self.url is not None:
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("media url must be absolute http(s)")
        return self


class ActionRequest(BaseModel):
    session: Session
    url: str = Field(..., min_length=1)
    # Keep in sync with app.recipes.RECIPES.
    recipe: Literal["x_post"] | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    script: str | None = None
    media: list[MediaItem] = Field(default_factory=list, max_length=4)
    screenshot: bool = False
    timeout_ms: int = Field(30_000, ge=5_000, le=120_000)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_mode(self) -> ActionRequest:
        if bool(self.recipe) == bool(self.script):
            raise ValueError("exactly one of recipe or script is required")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http or https URL")
        if self.recipe:
            from app.recipes import RECIPE_PARAM_MODELS

            params_model = RECIPE_PARAM_MODELS.get(self.recipe)
            if params_model is not None:
                self.params = params_model.model_validate(self.params).model_dump(exclude_none=True)
        return self


@dataclass(frozen=True)
class ActionResult:
    status: str
    result: Any
    log: list[str]
    final_url: str | None
    screenshot_base64: str | None


_action_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _action_semaphore
    if _action_semaphore is None:
        _action_semaphore = asyncio.Semaphore(ACTION_MAX_CONCURRENT)
    return _action_semaphore


async def _resolve_media(media: list[MediaItem], dest: Path) -> list[str]:
    paths: list[str] = []
    for index, item in enumerate(media):
        if item.data_base64 is not None:
            try:
                blob = base64.b64decode(item.data_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ActionError(f"media[{index}] is not valid base64", status_code=400) from exc
            name = item.filename or f"media{index}.bin"
        elif item.url is not None:
            fetched = await asset_fetcher.fetch_and_process_asset(item.url, None, None, None)
            if fetched.get("status") != "success":
                raise ActionError(f"media[{index}] fetch failed: {fetched.get('error')}", status_code=502)
            blob = base64.b64decode(fetched["data"])
            ext = _EXT_BY_CT.get(fetched.get("content_type", ""), "")
            name = item.filename or f"media{index}{ext}"
        else:  # unreachable: MediaItem validates exactly one source
            raise ActionError(f"media[{index}] has no source", status_code=400)
        path = dest / Path(name).name  # strip any directory component
        await asyncio.to_thread(path.write_bytes, blob)
        paths.append(str(path))
    return paths


def _build_worker_payload(request: ActionRequest, media_paths: list[str]) -> dict:
    session = request.session
    return {
        "url": request.url,
        "recipe": request.recipe,
        "params": request.params,
        "script": request.script,
        "screenshot": request.screenshot,
        "timeout_ms": request.timeout_ms,
        "cookies": [cookie.to_playwright() for cookie in session.cookies],
        "user_agent": session.user_agent,
        "viewport": session.viewport.model_dump() if session.viewport else None,
        "locale": session.locale,
        "timezone": session.timezone,
        "extra_headers": session.extra_headers or None,
        "media_paths": media_paths,
    }


async def run_action(request: ActionRequest) -> ActionResult:
    sem = _get_semaphore()
    async with sem:
        tmp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="scrapi-action-"))
        try:
            media_paths = await _resolve_media(request.media, tmp_dir)
            payload = _build_worker_payload(request, media_paths)
            async with browser_slot():
                return await _run_in_subprocess(payload, request.timeout_ms)
        finally:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)


async def _run_in_subprocess(payload: dict, step_timeout_ms: int) -> ActionResult:
    timeout_ms = max(ACTION_RENDER_TIMEOUT_MS, step_timeout_ms + 15_000)
    result = await run_json_worker("app.action_worker", payload, timeout_ms, ActionError, "action")
    return ActionResult(
        status="success",
        result=result.get("result"),
        log=result.get("log") or [],
        final_url=result.get("final_url"),
        screenshot_base64=result.get("screenshot_base64"),
    )
