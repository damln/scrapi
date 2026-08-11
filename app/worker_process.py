from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerProcessResult:
    stdout: bytes
    stderr: bytes
    returncode: int


async def _terminate_process_group(process: asyncio.subprocess.Process, pgid: int) -> None:
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
        await _terminate_process_group(process, pgid)
