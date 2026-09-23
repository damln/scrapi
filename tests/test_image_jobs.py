import asyncio
import base64
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import config, image_jobs, image_routes, image_worker
from app.chatgpt_browser import GenerationError, normalize_session
from app.image_jobs import ImageGenerationRequest, ImageJobs, generate_images, prepare_payload
from app.main import app
from app.worker_process import WorkerProcessResult
from tests.conftest import AUTH_HEADER

SESSION = {"cookies": [{"name": "session", "value": "PRIVATE-COOKIE", "domain": ".chatgpt.com"}]}
PAYLOAD = {"prompt": "a fox", "session": SESSION}
CONVERSATION_URL = "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize("conversation_url", [None, CONVERSATION_URL, CONVERSATION_URL + "/"])
def test_optional_conversation_reaches_worker(client, monkeypatch, conversation_url):
    generate = AsyncMock(return_value={"images": [], "conversation_url": CONVERSATION_URL})
    monkeypatch.setattr(image_worker.ChatGPTBrowser, "generate", generate)
    app.state.image_jobs.backend = image_worker.run
    response = client.post(
        "/api/v1/images/generations",
        json={**PAYLOAD, "conversation_url": conversation_url},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 202
    client.portal.call(lambda: asyncio.gather(*app.state.image_jobs.tasks))
    job = client.get(response.json()["poll_url"], headers=AUTH_HEADER).json()
    assert job["status"] == "completed"
    assert generate.call_args.args[-1] == (CONVERSATION_URL if conversation_url else None)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/c/123",
        "http://chatgpt.com/c/123",
        CONVERSATION_URL + "?redirect=https://example.com",
        CONVERSATION_URL + "#fragment",
        CONVERSATION_URL.replace("chatgpt.com", "chatgpt.com.evil.test"),
        CONVERSATION_URL.replace("chatgpt.com", "user@chatgpt.com"),
        CONVERSATION_URL.replace("/c/", "/share/"),
        "https://chatgpt.com/c/../settings",
    ],
)
def test_invalid_conversation_url_rejected_before_queue(client, url):
    backend = AsyncMock()
    app.state.image_jobs.backend = backend
    response = client.post("/api/v1/images/generations", json={**PAYLOAD, "conversation_url": url}, headers=AUTH_HEADER)
    assert response.status_code == 422
    backend.assert_not_called()


def test_project_conversation_url_is_supported():
    url = CONVERSATION_URL.replace("/c/", "/g/g-p-123-example/c/")
    assert ImageGenerationRequest(**PAYLOAD, conversation_url=url).conversation_url == url


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/images/generations"),
        ("GET", "/api/v1/images/jobs/unknown"),
        ("DELETE", "/api/v1/images/jobs/unknown"),
    ],
)
def test_images_require_scrapi_auth(client, method, path):
    assert client.request(method, path, json=PAYLOAD).status_code == 401


def test_submit_poll_delete_and_proxy(client, monkeypatch):
    result = {"images": [{"mime_type": "image/png", "b64_json": "aW1hZ2U="}], "text": ""}
    backend = AsyncMock(return_value=result)
    app.state.image_jobs.backend = backend
    monkeypatch.setenv("PROXY_URL", "socks5://proxy.test:1080")
    image = {"mime_type": "image/png", "b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\ntest").decode()}
    response = client.post("/api/v1/images/generations", json={**PAYLOAD, "images": [image]}, headers=AUTH_HEADER)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    url = response.json()["poll_url"]
    assert response.headers["location"] == url
    client.portal.call(lambda: asyncio.gather(*app.state.image_jobs.tasks))
    job = client.get(url, headers=AUTH_HEADER)
    assert job.json()["status"] == "completed"
    assert job.json()["result"] == result
    assert job.headers["cache-control"] == "no-store"
    assert "PRIVATE-COOKIE" not in job.text
    assert client.delete(url, headers=AUTH_HEADER).status_code == 204
    assert client.get(url, headers=AUTH_HEADER).status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        {"prompt": " "},
        {"session": "PRIVATE-COOKIE"},
        {"session": {"cookies": [{"domain": "other.test", "value": "PRIVATE-COOKIE"}]}},
        {"images": [{"mime_type": "image/png", "b64_json": "PRIVATE-COOKIE"}]},
        {"images": [{"mime_type": "image/png", "b64_json": "aGVsbG8="}]},
        {"proxy_profile": "unknown"},
    ],
)
def test_bad_input_is_rejected_without_secret_echo(client, extra):
    response = client.post("/api/v1/images/generations", json={**PAYLOAD, **extra}, headers=AUTH_HEADER)
    assert response.status_code in {400, 422}
    assert "PRIVATE-COOKIE" not in response.text


def test_streamed_body_limit(client, monkeypatch):
    monkeypatch.setattr(image_routes, "MAX_BODY", 20)
    response = client.post(
        "/api/v1/images/generations", content=iter([b'{"prompt":"', b"x" * 30, b'"}']), headers=AUTH_HEADER
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_session_file_and_named_proxy(tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    path.write_text(json.dumps(SESSION))
    monkeypatch.setattr(config, "CHATGPT_SESSION_FILE", str(path))
    monkeypatch.setenv("SCRAPI_PROXY_PROFILES_JSON", '{"m1":"socks5://m1.test:1080"}')
    payload = await prepare_payload(ImageGenerationRequest(prompt="fox", proxy_profile="m1"))
    assert payload["proxy_url"] == "socks5://m1.test:1080"
    assert payload["session"]["storage_state"]["cookies"][0]["value"] == "PRIVATE-COOKIE"
    path.write_text("invalid JSON")
    with pytest.raises(HTTPException, match="session_missing_or_invalid"):
        await prepare_payload(ImageGenerationRequest(prompt="fox"))


@pytest.mark.asyncio
async def test_serial_capacity_expiry_and_deletion():
    release = asyncio.Event()
    calls = []

    async def backend(payload):
        calls.append(payload["prompt"])
        await release.wait()
        return {"images": []}

    jobs = ImageJobs(backend)
    submitted = [jobs.submit({"prompt": str(i)}) for i in range(4)]
    with pytest.raises(HTTPException) as full:
        jobs.submit({"prompt": "fifth"})
    assert full.value.status_code == 429
    await asyncio.sleep(0)
    assert calls == ["0"]
    with pytest.raises(HTTPException) as active:
        jobs.delete(submitted[0].id)
    assert active.value.status_code == 409
    release.set()
    await asyncio.gather(*jobs.tasks)
    assert calls == ["0", "1", "2", "3"]
    jobs.expires[submitted[0].id] = 0
    with pytest.raises(HTTPException) as expired:
        jobs.get(submitted[0].id)
    assert expired.value.status_code == 404
    await jobs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GenerationError("session_expired"), "session_expired"),
        (RuntimeError("PRIVATE-COOKIE"), "browser_error"),
        (TimeoutError(), "generation_timeout"),
    ],
)
async def test_job_failures_are_sanitized(error, code):
    jobs = ImageJobs(AsyncMock(side_effect=error))
    payload = {"session": SESSION}
    job = jobs.submit(payload)
    await asyncio.gather(*jobs.tasks)
    assert jobs.get(job.id).error == code
    assert not payload
    await jobs.close()


@pytest.mark.asyncio
async def test_deadline_and_shutdown_cancel_backend():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def backend(payload):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    jobs = ImageJobs(backend, timeout=0.02)
    job = jobs.submit({})
    await asyncio.gather(*jobs.tasks)
    assert cancelled.is_set()
    assert jobs.get(job.id).error == "generation_timeout"
    cancelled.clear()
    started.clear()
    jobs = ImageJobs(backend)
    jobs.start()
    jobs.submit({})
    await started.wait()
    jobs.submit({})
    await jobs.close()
    assert cancelled.is_set()
    assert not jobs.tasks
    assert not jobs.items


@pytest.mark.asyncio
async def test_worker_receives_proxy_and_session_and_hides_stderr(monkeypatch):
    worker = AsyncMock(return_value=WorkerProcessResult(b'{"result":{"images":[]}}', b"", 0))
    monkeypatch.setattr(image_jobs, "run_worker_process", worker)
    payload = await prepare_payload(ImageGenerationRequest(**PAYLOAD, proxy_profile="direct"))
    assert await generate_images(payload) == {"images": []}
    sent = json.loads(worker.call_args.kwargs["input_bytes"])
    assert sent["proxy_url"] == ""
    assert sent["session"]["storage_state"]["cookies"][0]["value"] == "PRIVATE-COOKIE"
    worker.return_value = WorkerProcessResult(b"", b"PRIVATE-COOKIE", 1)
    with pytest.raises(GenerationError, match="^browser_worker_failed$"):
        await generate_images(payload)


def test_session_export_preserves_profile_and_filters_domains():
    session = normalize_session(
        {
            **SESSION,
            "locale": "en-US",
            "timezone": "Europe/Madrid",
            "cookies": [
                {**SESSION["cookies"][0], "sameSite": "no_restriction", "expirationDate": 123},
                {"name": "other", "value": "secret", "domain": "other.test"},
            ],
        }
    )
    cookies = session["storage_state"]["cookies"]
    assert len(cookies) == 1
    assert cookies[0]["sameSite"] == "None"
    assert cookies[0]["expires"] == 123
    assert session["timezone_id"] == "Europe/Madrid"


def test_live_docs_include_image_contract(client):
    docs = client.get("/api/v1/agent").text
    assert "POST /api/v1/images/generations" in docs
    assert "GET /api/v1/images/jobs/{job_id}" in docs
    assert "SCRAPI_CHATGPT_SESSION_FILE" in docs
