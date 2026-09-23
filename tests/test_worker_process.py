import asyncio
import signal
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.worker_process import WorkerError, WorkerProcessResult, run_json_worker, run_worker_process


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


class _ExampleError(WorkerError):
    pass


def _worker_result(stdout: bytes, *, returncode: int = 0, stderr: bytes = b"") -> WorkerProcessResult:
    return WorkerProcessResult(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.mark.asyncio
async def test_json_worker_returns_successful_result():
    worker = AsyncMock(return_value=_worker_result(b'{"status": "success", "value": 1}'))

    with patch("app.worker_process.run_worker_process", new=worker):
        result = await run_json_worker("app.example_worker", {"url": "x"}, 2_000, _ExampleError, "Example")

    assert result == {"status": "success", "value": 1}
    assert worker.await_args.kwargs["input_bytes"] == b'{"url": "x"}'
    assert worker.await_args.kwargs["timeout_seconds"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "message", "status_code"),
    [
        (TimeoutError(), "Example timeout (2000ms)", 504),
        (_worker_result(b"", returncode=3, stderr=b"boom\n"), "example_worker exit 3: boom", 502),
        (_worker_result(b"not json"), "example_worker returned invalid JSON", 502),
        (_worker_result(b'{"status": "error", "status_code": 504, "error": "slow"}'), "slow", 504),
        (_worker_result(b'{"status": "error"}'), "Example failed", 502),
    ],
)
async def test_json_worker_maps_failures_to_the_caller_error(outcome, message, status_code):
    worker = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)

    with patch("app.worker_process.run_worker_process", new=worker), pytest.raises(_ExampleError) as exc_info:
        await run_json_worker("app.example_worker", {}, 2_000, _ExampleError, "Example")

    assert str(exc_info.value) == message
    assert exc_info.value.status_code == status_code
