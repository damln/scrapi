"""Tests for the `obscura` provider — first entry in the default fallback chain.

The CLI itself is not invoked here; we mock `app.fetcher.fetch_with_obscura`
to assert dispatch/forwarding behavior. End-to-end CLI behavior (binary
present, stealth flag, real network) is covered by manual smoke tests.
"""

from unittest.mock import AsyncMock, patch

from tests.conftest import AUTH_HEADER


SIMPLE_HTML = "<html><head><title>Test</title></head><body><p>Hello obscura</p></body></html>"


# ---------------------------------------------------------------------------
# Default order puts obscura first
# ---------------------------------------------------------------------------


def test_obscura_is_first_in_default_provider_order():
    from app.fetcher import DEFAULT_PROVIDER_ORDER

    assert DEFAULT_PROVIDER_ORDER[0] == "obscura"
    assert DEFAULT_PROVIDER_ORDER[1] == "scrapling"


# ---------------------------------------------------------------------------
# /api/v1/content — obscura provider succeeds and returns no http metadata
# ---------------------------------------------------------------------------


@patch("app.fetcher.fetch_with_obscura", new_callable=AsyncMock)
def test_content_obscura_provider_success(mock_obscura, client):
    mock_obscura.return_value = (SIMPLE_HTML, {})

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "obscura"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "obscura"
    # obscura's CLI doesn't surface HTTP status/headers, so the response
    # has no `http` key — same shape as cloudflare/firecrawl results.
    assert "http" not in result
    mock_obscura.assert_awaited_once()


@patch("app.fetcher.fetch_with_obscura", new_callable=AsyncMock)
def test_content_obscura_provider_forwards_wait_options(mock_obscura, client):
    mock_obscura.return_value = (SIMPLE_HTML, {})

    resp = client.get(
        "/api/v1/content",
        params={
            "urls": "https://example.com",
            "provider_order": "obscura",
            "wait_until": "networkidle",
            "wait_for_selector": ".listing-card",
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    mock_obscura.assert_awaited_once_with(
        "https://example.com",
        wait_until="networkidle",
        wait_for_selector=".listing-card",
    )


# ---------------------------------------------------------------------------
# Fallback: obscura raises -> scrapling is tried next
# ---------------------------------------------------------------------------


@patch("app.fetcher._fetch_with_scrapling", new_callable=AsyncMock)
@patch("app.fetcher.fetch_with_obscura", new_callable=AsyncMock)
def test_obscura_failure_falls_through_to_scrapling(mock_obscura, mock_scrapling, client):
    # Obscura blows up (e.g. binary missing, exit non-zero, empty stdout).
    # The chain must continue — scrapling provides the answer.
    mock_obscura.side_effect = RuntimeError("obscura exit 1: binary not found")
    mock_scrapling.return_value = (
        SIMPLE_HTML,
        {"status": 200, "headers": {"content-type": "text/html"}, "redirect_history": None},
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "obscura,scrapling"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "scrapling"
    # Both providers were attempted, in order.
    mock_obscura.assert_awaited_once()
    mock_scrapling.assert_awaited_once()


# ---------------------------------------------------------------------------
# `obscura` is accepted as a valid provider
# ---------------------------------------------------------------------------


def test_obscura_is_a_valid_provider(client):
    # Sanity check: the validator accepts the new name. We don't actually
    # need a successful fetch — the request only needs to clear validation.
    with patch("app.fetcher.fetch_with_obscura", new_callable=AsyncMock) as mock_obscura:
        mock_obscura.return_value = (SIMPLE_HTML, {})
        resp = client.get(
            "/api/v1/content",
            params={"urls": "https://example.com", "provider_order": "obscura"},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert "error" not in payload
