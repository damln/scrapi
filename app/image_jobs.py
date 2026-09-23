"""Bounded, process-local image jobs. Run a single API worker per instance."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from app import config
from app.browser_budget import browser_slot
from app.chatgpt_browser import GenerationError, load_session, normalize_session
from app.proxy_profiles import ProxyProfileError, resolve_proxy_profile
from app.worker_process import run_worker_process

logger = logging.getLogger(__name__)
MAX_IMAGE = 10 * 1024 * 1024
MAX_BODY = 30 * 1024 * 1024
MAX_JOBS = 4
RETENTION = 3600
GENERATION_TIMEOUT = 600


class InputImage(BaseModel):
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    b64_json: str = Field(min_length=1, max_length=MAX_IMAGE * 4 // 3 + 4, repr=False)

    def validate_content(self) -> None:
        try:
            data = base64.b64decode(self.b64_json, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, "Invalid image base64") from None
        signatures = {
            "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        }
        if not signatures[self.mime_type] or len(data) > MAX_IMAGE:
            raise HTTPException(422, "Invalid image type or image exceeds 10 MiB")


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    conversation_url: str | None = Field(
        None,
        max_length=512,
        description="Optional https://chatgpt.com/c/<UUID> URL of an existing conversation accessible to this session. Omit for a new chat. Can reuse result.conversation_url from a previous job.",
    )
    images: list[InputImage] = Field(default_factory=list, max_length=4)
    session: dict | list[dict] | None = Field(
        None,
        repr=False,
        description="Cookie export or Playwright storage state with optional user_agent, locale, timezone and viewport. Omit to use SCRAPI_CHATGPT_SESSION_FILE. Never returned or persisted.",
    )
    proxy_profile: str = Field(
        "current", description="Uses Scrapi's PROXY_URL by default. Also accepts direct or a named profile."
    )

    model_config = {"extra": "forbid"}

    @field_validator("conversation_url")
    @classmethod
    def valid_conversation_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(
            r"https://chatgpt\.com/(?:g/[A-Za-z0-9-]+/)?c/"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/?",
            value,
        ):
            raise ValueError("Expected a ChatGPT conversation URL")
        return value.rstrip("/")

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt cannot be blank")
        return value


class ImageJob(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    poll_url: str
    result: dict | None = None
    error: str | None = None


async def prepare_payload(request: ImageGenerationRequest) -> dict:
    for image in request.images:
        image.validate_content()
    try:
        proxy_url = resolve_proxy_profile(request.proxy_profile)
    except ProxyProfileError:
        raise HTTPException(400, "Invalid proxy profile or proxy configuration") from None
    try:
        if request.session is not None:
            session = normalize_session(request.session)
        elif config.CHATGPT_SESSION_FILE:
            session = await asyncio.to_thread(load_session, Path(config.CHATGPT_SESSION_FILE))
        else:
            raise HTTPException(422, "Supply session or configure SCRAPI_CHATGPT_SESSION_FILE")
    except GenerationError:
        raise HTTPException(422, "session_missing_or_invalid") from None
    return {
        "prompt": request.prompt,
        "conversation_url": request.conversation_url,
        "images": [image.model_dump() for image in request.images],
        "session": session,
        "proxy_url": proxy_url,
    }


async def generate_images(payload: dict) -> dict:
    process = await run_worker_process(
        "app.image_worker",
        input_bytes=json.dumps(payload).encode(),
        timeout_seconds=GENERATION_TIMEOUT,
    )
    if process.returncode:
        raise GenerationError("browser_worker_failed")
    try:
        response = json.loads(process.stdout)
        if response.get("error"):
            raise GenerationError(response["error"])
        result = response["result"]
        if not isinstance(result, dict):
            raise GenerationError("browser_worker_invalid_response")
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GenerationError("browser_worker_invalid_response") from None


class ImageJobs:
    def __init__(
        self,
        backend: Callable[[dict], Awaitable[dict]] = generate_images,
        timeout: float = GENERATION_TIMEOUT,
    ):
        self.backend = backend
        self.timeout = timeout
        self.items: dict[str, ImageJob] = {}
        self.expires: dict[str, float] = {}
        self.tasks: set[asyncio.Task] = set()
        self.lock = asyncio.Lock()
        self.closed = False
        self.cleaner: asyncio.Task | None = None

    def prune(self) -> None:
        for key, expires in list(self.expires.items()):
            if expires <= time.monotonic():
                self.items.pop(key, None)
                del self.expires[key]

    def submit(self, payload: dict) -> ImageJob:
        self.prune()
        if self.closed:
            raise HTTPException(503, "Server shutting down")
        if len(self.items) >= MAX_JOBS:
            raise HTTPException(429, "Job capacity reached. Delete completed jobs or wait for expiry.")
        job_id = uuid.uuid4().hex
        job = ImageJob(id=job_id, status="queued", poll_url=f"/api/v1/images/jobs/{job_id}")
        self.items[job_id] = job
        task = asyncio.create_task(self.run(job, payload))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job.model_copy()

    async def run(self, job: ImageJob, payload: dict) -> None:
        try:
            async with self.lock:
                async with asyncio.timeout(self.timeout):
                    async with browser_slot():
                        job.status = "running"
                        logger.info("Image job %s running", job.id)
                        job.result = await self.backend(payload)
                        job.status = "completed"
        except GenerationError as exc:
            job.status, job.error = "failed", str(exc)
        except TimeoutError:
            job.status, job.error = "failed", "generation_timeout"
        except asyncio.CancelledError:
            job.status, job.error = "failed", "server_shutdown"
            raise
        except Exception:
            job.status, job.error = "failed", "browser_error"
        finally:
            payload.clear()
            self.expires[job.id] = time.monotonic() + RETENTION
            logger.info("Image job %s %s", job.id, job.status)

    def get(self, job_id: str) -> ImageJob:
        self.prune()
        if job_id not in self.items:
            raise HTTPException(404, "Job not found or expired")
        return self.items[job_id]

    def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status in {"queued", "running"}:
            raise HTTPException(409, "Job is still active")
        del self.items[job_id]
        self.expires.pop(job_id, None)

    async def cleanup(self) -> None:
        while True:
            await asyncio.sleep(60)
            self.prune()

    def start(self) -> None:
        self.cleaner = asyncio.create_task(self.cleanup())

    async def close(self) -> None:
        self.closed = True
        if self.cleaner:
            self.cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleaner
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.items.clear()
        self.expires.clear()
