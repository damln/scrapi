from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WorkerProcessResult:
    stdout: bytes
    stderr: bytes
    returncode: int


async def terminate_process_group(process: asyncio.subprocess.Process, pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning("killpg(%s) denied: %s", pgid, exc)

    if process.returncode is None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=3)


async def run_worker_process(
    module: str,
    *args: str,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> WorkerProcessResult:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        *args,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    pgid = process.pid

    try:
        communication = process.communicate(input_bytes)
        if timeout_seconds is not None:
            stdout, stderr = await asyncio.wait_for(communication, timeout=timeout_seconds)
        else:
            stdout, stderr = await communication

        if process.returncode is None:
            raise RuntimeError(f"{module} exited without a return code")
        return WorkerProcessResult(stdout=stdout, stderr=stderr, returncode=process.returncode)
    finally:
        await terminate_process_group(process, pgid)


async def run_json_worker(
    module: str,
    payload: dict[str, Any],
    timeout_ms: int,
    error_cls: type[WorkerError],
    label: str,
) -> dict[str, Any]:
    """Run a one-shot worker that answers a JSON request with a `status: success` JSON result."""
    worker_name = module.rsplit(".", 1)[-1]
    try:
        process_result = await run_worker_process(
            module,
            input_bytes=json.dumps(payload).encode("utf-8"),
            timeout_seconds=timeout_ms / 1000,
        )
    except TimeoutError as exc:
        raise error_cls(f"{label} timeout ({timeout_ms}ms)", status_code=504) from exc

    stderr_text = process_result.stderr.decode("utf-8", errors="replace").strip()
    if process_result.returncode != 0:
        raise error_cls(f"{worker_name} exit {process_result.returncode}: {stderr_text[:500]}")

    try:
        result: dict[str, Any] = json.loads(process_result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise error_cls(f"{worker_name} returned invalid JSON") from exc

    if result.get("status") != "success":
        raise error_cls(result.get("error") or f"{label} failed", status_code=int(result.get("status_code") or 502))
    return result
