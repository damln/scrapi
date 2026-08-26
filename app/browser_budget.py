from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import BROWSER_MAX_CONCURRENT

_browser_semaphore: asyncio.Semaphore | None = None


def _get_browser_semaphore() -> asyncio.Semaphore:
    global _browser_semaphore
    if _browser_semaphore is None:
        _browser_semaphore = asyncio.Semaphore(BROWSER_MAX_CONCURRENT)
    return _browser_semaphore


@asynccontextmanager
async def browser_slot() -> AsyncIterator[None]:
    """Share one process-local Chromium budget across every browser feature."""
    async with _get_browser_semaphore():
        yield
