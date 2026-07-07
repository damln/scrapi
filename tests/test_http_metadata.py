from unittest.mock import AsyncMock, patch

import respx
from httpx import Response

from app.agent_examples import EXAMPLE_HTML
from tests.conftest import AUTH_HEADER

SIMPLE_HTML = EXAMPLE_HTML + ("x" * 260)


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_returns_http_metadata(mock_fetch, client):
    mock_fetch.return_value = (
        SIMPLE_HTML,
        {"status": 200, "redirect_history": None},
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "cloak"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["http"]["status"] == 200
    assert "headers" not in result["http"]
    assert result["http"]["redirect_history"] is None


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_with_redirect_history(mock_fetch, client):
    mock_fetch.return_value = (
        SIMPLE_HTML,
        {
            "status": 200,
            "redirect_history": [
                {"status": 301, "url": "http://example.com"},
            ],
        },
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "http://example.com", "provider_order": "cloak"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    http = result["http"]
    assert http["status"] == 200
    assert len(http["redirect_history"]) == 1
    assert http["redirect_history"][0]["status"] == 301
    assert http["redirect_history"][0]["url"] == "http://example.com"
    assert "headers" not in http["redirect_history"][0]


def test_content_rejects_invalid_wait_until(client):
    resp = client.get(
        "/api/v1/content",
        params={
            "urls": "https://example.com",
            "provider_order": "cloak",
            "wait_until": "commit",
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert "Invalid wait_until" in payload["error"]
    assert payload["results"] == []


@patch("app.fetcher.PROVIDER_API_KEYS", {"firecrawl": "fake-key"})
@patch("app.fetcher.fetch_with_firecrawl")
def test_content_firecrawl_has_no_http_metadata(mock_fc, client):
    mock_fc.return_value = SIMPLE_HTML

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "firecrawl"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "firecrawl"
    assert "http" not in result


@respx.mock
def test_asset_returns_http_metadata(client):
    respx.get("https://cdn.example.com/style.css").mock(
        return_value=Response(200, content=b"body { color: red; }", headers={"content-type": "text/css"})
    )

    resp = client.get(
        "/api/v1/asset",
        params={"url": "https://cdn.example.com/style.css"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "success"
    assert result["http"]["status"] == 200
    assert "headers" not in result["http"]
    assert result["http"]["redirect_history"] is None


@respx.mock
def test_asset_returns_redirect_history(client):
    redirect_1 = Response(301, headers={"location": "https://cdn.example.com/v2/logo.png", "content-length": "0"})
    final = Response(
        200,
        content=_make_1x1_png(),
        headers={"content-type": "image/png"},
    )

    respx.get("https://cdn.example.com/logo.png").mock(return_value=redirect_1)
    respx.get("https://cdn.example.com/v2/logo.png").mock(return_value=final)

    resp = client.get(
        "/api/v1/asset",
        params={"url": "https://cdn.example.com/logo.png"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "success"
    http = result["http"]
    assert http["status"] == 200
    assert http["redirect_history"] is not None
    assert len(http["redirect_history"]) == 1
    assert http["redirect_history"][0]["status"] == 301


@respx.mock
def test_asset_error_has_no_http_metadata(client):
    respx.get("https://cdn.example.com/missing.png").mock(return_value=Response(404))

    resp = client.get(
        "/api/v1/asset",
        params={"url": "https://cdn.example.com/missing.png"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "error"
    assert "http" not in result


def _make_1x1_png() -> bytes:
    """Smallest valid 1x1 transparent PNG."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()
