"""Tests for `app.diagnostics` and the egress_ip / sibling-http-metadata
fields they expose on /api/v1/content responses.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import AUTH_HEADER


SIMPLE_HTML = "<html><head><title>Test</title></head><body><p>Hi</p></body></html>"


# ---------------------------------------------------------------------------
# get_egress_ip — caches first response, swallows errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_egress_ip_caches_first_response():
    from app import diagnostics

    diagnostics._egress_ip = None
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"ip": "1.2.3.4"}
    fake_resp.raise_for_status = MagicMock()
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=fake_resp)

    with patch.object(diagnostics, "_client", fake_client):
        ip1 = await diagnostics.get_egress_ip()
        ip2 = await diagnostics.get_egress_ip()

    assert ip1 == "1.2.3.4"
    assert ip2 == "1.2.3.4"
    # Second call hit the cache, not the network.
    fake_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_egress_ip_returns_none_on_failure():
    from app import diagnostics

    diagnostics._egress_ip = None
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("network down"))

    with patch.object(diagnostics, "_client", fake_client):
        ip = await diagnostics.get_egress_ip()

    assert ip is None
    assert diagnostics._egress_ip is None  # not cached on failure


# ---------------------------------------------------------------------------
# fetch_sibling_http_metadata — empty dict on failure, structured on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_sibling_http_metadata_success():
    from app import diagnostics

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"server": "DataDome", "content-type": "text/html"}
    fake_resp.history = []
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=fake_resp)

    with patch.object(diagnostics, "_client", fake_client):
        meta = await diagnostics.fetch_sibling_http_metadata("https://example.com")

    assert meta["status"] == 200
    assert meta["headers"]["server"] == "DataDome"
    assert meta["source"] == "sibling-httpx"
    assert meta["redirect_history"] is None


@pytest.mark.asyncio
async def test_fetch_sibling_http_metadata_returns_empty_on_failure():
    from app import diagnostics

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("DNS fail"))

    with patch.object(diagnostics, "_client", fake_client):
        meta = await diagnostics.fetch_sibling_http_metadata("https://example.com")

    # Empty dict — the caller treats this as "no http info" and continues
    # rather than failing the entire fetch.
    assert meta == {}


# ---------------------------------------------------------------------------
# /api/v1/content includes egress_ip when discovered
# ---------------------------------------------------------------------------


@patch("app.fetcher.get_egress_ip", new_callable=AsyncMock)
@patch("app.fetcher._fetch_with_scrapling", new_callable=AsyncMock)
def test_content_response_includes_egress_ip(mock_fetch, mock_egress, client):
    mock_egress.return_value = "203.0.113.42"
    mock_fetch.return_value = (
        SIMPLE_HTML,
        {"status": 200, "headers": {"content-type": "text/html"}, "redirect_history": None},
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "scrapling"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["egress_ip"] == "203.0.113.42"


@patch("app.fetcher.get_egress_ip", new_callable=AsyncMock)
@patch("app.fetcher._fetch_with_scrapling", new_callable=AsyncMock)
def test_content_response_omits_egress_ip_when_unknown(mock_fetch, mock_egress, client):
    # When discovery has not (yet) succeeded, the field is absent —
    # never returned as null. Keeps the response shape clean.
    mock_egress.return_value = None
    mock_fetch.return_value = (
        SIMPLE_HTML,
        {"status": 200, "headers": {"content-type": "text/html"}, "redirect_history": None},
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "scrapling"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert "egress_ip" not in result


# ---------------------------------------------------------------------------
# Obscura now returns sibling http metadata
# ---------------------------------------------------------------------------


@patch("app.fetcher.get_egress_ip", new_callable=AsyncMock)
@patch("app.fetcher.fetch_with_obscura", new_callable=AsyncMock)
def test_obscura_response_includes_sibling_http(mock_obscura, mock_egress, client):
    mock_egress.return_value = "203.0.113.42"
    mock_obscura.return_value = (
        SIMPLE_HTML,
        {
            "source": "sibling-httpx",
            "status": 403,
            "headers": {"server": "DataDome"},
            "redirect_history": None,
        },
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "obscura"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["provider"] == "obscura"
    assert result["http"]["source"] == "sibling-httpx"
    assert result["http"]["status"] == 403
    assert result["http"]["headers"]["server"] == "DataDome"
