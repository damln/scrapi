import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.conftest import AUTH_HEADER


def test_capture_requires_auth(client):
    response = client.post("/api/v1/capture", json={"url": "https://example.com"})
    assert response.status_code in (401, 403)


def test_capture_rejects_invalid_url(client):
    response = client.post("/api/v1/capture", json={"url": "file:///etc/passwd"}, headers=AUTH_HEADER)
    assert response.status_code == 422


@patch("app.main.capture_browser", new_callable=AsyncMock)
def test_capture_returns_portable_zip(mock_capture, client):
    async def fake_capture(request):
        output = Path(request.output_dir)
        output.mkdir(parents=True)
        screenshot = output / "screenshot.png"
        screenshot.write_bytes(b"png")
        return {
            "status": "success",
            "url": "https://example.com/",
            "http_status": 200,
            "files": {
                "screenshot": str(screenshot),
                "html": None,
                "har": None,
                "video": None,
                "resource_manifest": None,
            },
        }

    mock_capture.side_effect = fake_capture
    response = client.post(
        "/api/v1/capture",
        json={"url": "https://example.com", "html": False, "har": False},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-scrapi-http-status"] == "200"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"result.json", "screenshot.png"}
        result = json.loads(archive.read("result.json"))
        assert result["files"]["screenshot"] == "screenshot.png"

    internal = mock_capture.await_args.args[0]
    assert Path(internal.output_dir).parent.name.startswith("scrapi-capture-api-")
    assert internal.proxy_url == ""


def test_capture_rejects_unknown_proxy_profile(client):
    response = client.post(
        "/api/v1/capture",
        json={"url": "https://example.com", "proxy_profile": "missing"},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 400


@patch("app.main.capture_browser", new_callable=AsyncMock)
def test_screenshot_returns_single_jpeg(mock_capture, client):
    async def fake_capture(request):
        output = Path(request.output_dir)
        output.mkdir(parents=True)
        screenshot = output / "screenshot.jpg"
        screenshot.write_bytes(b"jpeg")
        return {
            "status": "success",
            "url": "https://example.com/",
            "http_status": 200,
            "viewport": {"width": request.width, "height": request.height},
            "screenshot": {"capped": False},
            "files": {"screenshot": str(screenshot)},
        }

    mock_capture.side_effect = fake_capture
    response = client.get(
        "/api/v1/screenshot",
        params={
            "url": "https://example.com",
            "viewport": "mobile",
            "quality": 99,
            "render_scale": 2,
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"] == 'inline; filename="screenshot-390x844.jpg"'
    assert response.headers["x-scrapi-screenshot-capped"] == "false"
    assert response.content == b"jpeg"
    internal = mock_capture.await_args.args[0]
    assert (internal.width, internal.height) == (390, 844)
    assert internal.screenshot_format == "jpeg"
    assert internal.screenshot_quality == 99
    assert internal.render_scale == 2
    assert internal.html is False
    assert internal.har is False


@patch("app.main.capture_browser", new_callable=AsyncMock)
def test_screenshot_returns_zip_for_multiple_viewports(mock_capture, client):
    async def fake_capture(request):
        output = Path(request.output_dir)
        output.mkdir(parents=True)
        screenshot = output / "screenshot.jpg"
        screenshot.write_bytes(f"{request.width}x{request.height}".encode())
        return {
            "status": "success",
            "url": "https://example.com/",
            "http_status": 200,
            "viewport": {"width": request.width, "height": request.height},
            "screenshot": {"capped": False},
            "files": {"screenshot": str(screenshot)},
        }

    mock_capture.side_effect = fake_capture
    response = client.get(
        "/api/v1/screenshot?url=https%3A%2F%2Fexample.com&viewport=mobile&viewport=desktop",
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "result.json",
            "screenshot-390x844.jpg",
            "screenshot-1440x1000.jpg",
        }
        result = json.loads(archive.read("result.json"))
        assert [item["viewport"] for item in result["results"]] == [
            {"width": 390, "height": 844},
            {"width": 1440, "height": 1000},
        ]


def test_screenshot_rejects_invalid_viewport(client):
    response = client.get(
        "/api/v1/screenshot",
        params={"url": "https://example.com", "viewport": "phone-ish"},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 400


def test_screenshot_rejects_invalid_url(client):
    response = client.get(
        "/api/v1/screenshot",
        params={"url": "file:///etc/passwd"},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 422
