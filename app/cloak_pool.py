from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import deque
from typing import Any

from app.worker_process import terminate_process_group

WORKER_STREAM_LIMIT_BYTES = 64 * 1024 * 1024


class CloakWorker:
    """One persistent subprocess owning one reusable CloakBrowser instance."""

    def __init__(self, max_requests: int) -> None:
        if max_requests < 1:
            raise ValueError("cloak worker request limit must be at least 1")
        self._process: asyncio.subprocess.Process | None = None
        self._proxy_url: str | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._max_requests = max_requests
        self._completed_requests = 0

    async def execute(self, payload: dict[str, Any], proxy_url: str) -> dict[str, Any]:
        if (
            self._process is None
            or self._process.returncode is not None
            or self._proxy_url != proxy_url
            or self._completed_requests >= self._max_requests
        ):
            await self.close()
            await self._start(proxy_url)

        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("cloak worker did not expose its protocol pipes")

        try:
            message = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
            process.stdin.write(message)
            await process.stdin.drain()
            raw_response = await process.stdout.readline()
            result = self._parse_response(raw_response)
            self._completed_requests += 1
            return result
        except (Exception, asyncio.CancelledError):
            await self.close()
            raise

    async def close(self) -> None:
        process = self._process
        stderr_task = self._stderr_task
        self._process = None
        self._proxy_url = None
        self._stderr_task = None
        self._completed_requests = 0

        if process is not None:
            await terminate_process_group(process, process.pid)

        if stderr_task is not None:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)

    async def _start(self, proxy_url: str) -> None:
        env = os.environ.copy()
        env["PROXY_URL"] = proxy_url
        self._stderr_tail.clear()
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.cloak_worker",
            "--serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=WORKER_STREAM_LIMIT_BYTES,
            start_new_session=True,
        )
        self._proxy_url = proxy_url
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        while line := await process.stderr.readline():
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_tail.append(text)

    def _stderr_detail(self) -> str:
        if not self._stderr_tail:
            return ""
        return f": {self._stderr_tail[-1][:500]}"

    def _parse_response(self, raw_response: bytes) -> dict[str, Any]:
        if not raw_response:
            raise RuntimeError(f"cloak worker exited before returning a result{self._stderr_detail()}")

        response = json.loads(raw_response.decode("utf-8", errors="replace"))
        if not isinstance(response, dict):
            raise TypeError("cloak worker returned a non-object response")
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "cloak worker failed"))

        result = response.get("result")
        if not isinstance(result, dict):
            raise TypeError("cloak worker returned an invalid result")
        return result


class CloakBrowserPool:
    """Bounded pool of persistent browser subprocesses.

    A worker handles one request at a time. Each request still receives a fresh
    browser context inside the worker, so cookies and storage are never shared.
    """

    def __init__(self, size: int, max_requests_per_worker: int) -> None:
        if size < 1:
            raise ValueError("cloak browser pool size must be at least 1")
        self._workers = [CloakWorker(max_requests_per_worker) for _ in range(size)]
        self._available: asyncio.Queue[CloakWorker] = asyncio.Queue(maxsize=size)
        for worker in self._workers:
            self._available.put_nowait(worker)

    async def execute(self, payload: dict[str, Any], proxy_url: str) -> dict[str, Any]:
        worker = await self._available.get()
        try:
            return await worker.execute(payload, proxy_url)
        finally:
            self._available.put_nowait(worker)

    async def close(self) -> None:
        await asyncio.gather(*(worker.close() for worker in self._workers))
