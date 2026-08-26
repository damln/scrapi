import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.cloak_pool import WORKER_STREAM_LIMIT_BYTES, CloakWorker


def _process(response: dict) -> Mock:
    process = Mock()
    process.pid = 4321
    process.returncode = None
    process.stdin = Mock()
    process.stdin.drain = AsyncMock()
    process.stdout = Mock()
    process.stdout.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
    process.stderr = Mock()
    process.stderr.readline = AsyncMock(return_value=b"")
    return process


@pytest.mark.asyncio
async def test_worker_reuses_process_for_matching_proxy():
    process = _process({"ok": True, "result": {"html": "<html></html>"}})
    worker = CloakWorker(max_requests=100)

    with (
        patch("app.cloak_pool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn,
        patch("app.cloak_pool.terminate_process_group", new=AsyncMock()) as terminate,
    ):
        first = await worker.execute({"url": "https://one.example"}, "socks5://proxy:1080")
        second = await worker.execute({"url": "https://two.example"}, "socks5://proxy:1080")
        await worker.close()

    assert first["html"] == "<html></html>"
    assert second["html"] == "<html></html>"
    spawn.assert_awaited_once()
    assert spawn.await_args.kwargs["limit"] == WORKER_STREAM_LIMIT_BYTES
    assert process.stdin.write.call_count == 2
    terminate.assert_awaited_once_with(process, process.pid)


@pytest.mark.asyncio
async def test_worker_restarts_when_proxy_changes():
    first_process = _process({"ok": True, "result": {"html": "first"}})
    second_process = _process({"ok": True, "result": {"html": "second"}})
    worker = CloakWorker(max_requests=100)

    with (
        patch(
            "app.cloak_pool.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[first_process, second_process]),
        ) as spawn,
        patch("app.cloak_pool.terminate_process_group", new=AsyncMock()) as terminate,
    ):
        await worker.execute({"url": "https://one.example"}, "")
        await worker.execute({"url": "https://two.example"}, "socks5://proxy:1080")
        await worker.close()

    assert spawn.await_count == 2
    assert terminate.await_count == 2


@pytest.mark.asyncio
async def test_worker_is_terminated_when_request_is_cancelled():
    process = _process({"ok": True, "result": {}})
    process.stdout.readline.side_effect = asyncio.CancelledError
    worker = CloakWorker(max_requests=100)

    with (
        patch("app.cloak_pool.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
        patch("app.cloak_pool.terminate_process_group", new=AsyncMock()) as terminate,
    ):
        with pytest.raises(asyncio.CancelledError):
            await worker.execute({"url": "https://example.com"}, "")

    terminate.assert_awaited_once_with(process, process.pid)


@pytest.mark.asyncio
async def test_worker_recycles_after_request_limit():
    first_process = _process({"ok": True, "result": {"html": "first"}})
    second_process = _process({"ok": True, "result": {"html": "second"}})
    worker = CloakWorker(max_requests=1)

    with (
        patch(
            "app.cloak_pool.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[first_process, second_process]),
        ) as spawn,
        patch("app.cloak_pool.terminate_process_group", new=AsyncMock()) as terminate,
    ):
        await worker.execute({"url": "https://one.example"}, "")
        await worker.execute({"url": "https://two.example"}, "")
        await worker.close()

    assert spawn.await_count == 2
    assert terminate.await_count == 2
