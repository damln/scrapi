import asyncio
import signal
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.worker_process import run_worker_process


def _process(*, returncode: int | None) -> Mock:
    process = Mock()
    process.pid = 4321
    process.returncode = returncode
    process.communicate = AsyncMock(return_value=(b"payload", b""))
    process.wait = AsyncMock(return_value=returncode)
    return process


@pytest.mark.asyncio
async def test_worker_process_uses_isolated_group_and_cleans_it_after_success():
    process = _process(returncode=0)

    with (
        patch("app.worker_process.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn,
        patch("app.worker_process.os.killpg") as killpg,
    ):
        result = await run_worker_process("app.example_worker", "--flag")

    assert result.stdout == b"payload"
    assert result.returncode == 0
    assert spawn.await_args.kwargs["start_new_session"] is True
    killpg.assert_called_once_with(4321, signal.SIGKILL)


@pytest.mark.asyncio
async def test_worker_process_cleans_group_and_reaps_worker_after_timeout():
    process = _process(returncode=None)
    process.communicate.side_effect = TimeoutError

    with (
        patch("app.worker_process.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
        patch("app.worker_process.os.killpg") as killpg,
    ):
        with pytest.raises(TimeoutError):
            await run_worker_process("app.example_worker", input_bytes=b"{}", timeout_seconds=0.1)

    killpg.assert_called_once_with(4321, signal.SIGKILL)
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_process_cleans_group_after_cancellation():
    process = _process(returncode=None)
    process.communicate.side_effect = asyncio.CancelledError

    with (
        patch("app.worker_process.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
        patch("app.worker_process.os.killpg") as killpg,
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_worker_process("app.example_worker")

    killpg.assert_called_once_with(4321, signal.SIGKILL)
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_process_ignores_an_already_gone_group():
    process = _process(returncode=0)

    with (
        patch("app.worker_process.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
        patch("app.worker_process.os.killpg", side_effect=ProcessLookupError),
    ):
        result = await run_worker_process("app.example_worker")

    assert result.returncode == 0
