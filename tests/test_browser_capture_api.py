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
