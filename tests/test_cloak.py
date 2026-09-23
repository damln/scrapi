"""Tests for the `cloak` provider — first entry in the default fallback chain.

The Chromium binary is not launched here; we mock `app.fetcher.fetch_with_cloak`
to assert dispatch / forwarding / fallthrough. End-to-end browser behavior
(real Chromium, real SOCKS5 egress) is covered by manual smoke tests against
the prod deployment.
"""

import json
import os
from unittest.mock import AsyncMock, Mock, patch

from app.cloak_worker import fetch, serve
from tests.conftest import AUTH_HEADER

SIMPLE_HTML = "<html><head><title>Test</title></head><body><p>Hello cloak</p>" + "x" * 260 + "</body></html>"


def test_worker_reuses_browser_with_fresh_context_per_url():
    first_context = Mock()
    second_context = Mock()
    first_page = first_context.new_page.return_value
    second_page = second_context.new_page.return_value
    first_page.goto.return_value = Mock(status=200)
    second_page.goto.return_value = Mock(status=200)
    first_page.content.return_value = SIMPLE_HTML
    second_page.content.return_value = SIMPLE_HTML
    browser = Mock()
    browser.new_context.side_effect = [first_context, second_context]

    with patch("app.cloak_worker.dismiss_cookies"):
        fetch(browser, "https://one.example", False, "load", None)
        fetch(browser, "https://two.example", False, "load", None)

    assert browser.new_context.call_count == 2
    first_context.close.assert_called_once()
    second_context.close.assert_called_once()
    browser.close.assert_not_called()


def test_worker_server_reports_browser_launch_failure(capsys):
    with patch("app.cloak_worker.launch_cloak_browser", side_effect=RuntimeError("cannot launch browser")):
        assert serve() == 1

    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "cannot launch browser"}


def test_cloak_is_first_in_default_provider_order():
    from app.fetcher import DEFAULT_PROVIDER_ORDER

    assert DEFAULT_PROVIDER_ORDER[0] == "cloak"
    assert DEFAULT_PROVIDER_ORDER[1] == "firecrawl"


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_success(mock_cloak, client):
    mock_cloak.return_value = (
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
    assert result["provider"] == "cloak"
    assert result["http"]["status"] == 200
    mock_cloak.assert_awaited_once()


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_forwards_wait_options(mock_cloak, client):
    mock_cloak.return_value = (SIMPLE_HTML, {"status": 200, "redirect_history": None})

    resp = client.get(
        "/api/v1/content",
        params={
            "urls": "https://example.com",
            "provider_order": "cloak",
            "wait_until": "networkidle",
            "wait_for_selector": ".listing-card",
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    mock_cloak.assert_awaited_once_with(
        "https://example.com",
        scroll_full=False,
        wait_until="networkidle",
        wait_for_selector=".listing-card",
        proxy_url="",
    )


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_allows_domcontentloaded_wait(mock_cloak, client):
    mock_cloak.return_value = (SIMPLE_HTML, {"status": 200, "redirect_history": None})

    resp = client.get(
        "/api/v1/content",
        params={
            "urls": "https://example.com",
            "provider_order": "cloak",
            "wait_until": "domcontentloaded",
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    mock_cloak.assert_awaited_once_with(
        "https://example.com",
        scroll_full=False,
        wait_until="domcontentloaded",
        wait_for_selector=None,
        proxy_url="",
    )


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_content_cloak_provider_forwards_named_proxy_profile(mock_cloak, client):
    mock_cloak.return_value = (SIMPLE_HTML, {"status": 200, "redirect_history": None})

    with patch.dict(
        os.environ,
        {"SCRAPI_PROXY_PROFILES_JSON": '{"residential_backup":"http://user:pass@proxy.example:8000"}'},
    ):
        resp = client.get(
            "/api/v1/content",
            params={
                "urls": "https://example.com",
                "provider_order": "cloak",
                "proxy_profile": "residential_backup",
            },
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    mock_cloak.assert_awaited_once_with(
        "https://example.com",
        scroll_full=False,
        wait_until=None,
        wait_for_selector=None,
        proxy_url="http://user:pass@proxy.example:8000",
    )


def test_content_rejects_invalid_proxy_profile(client):
    resp = client.get(
        "/api/v1/content",
        params={
            "urls": "https://example.com",
            "provider_order": "cloak",
            "proxy_profile": "missing",
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert "Invalid proxy_profile" in payload["error"]
    assert payload["profiles"] == ["current", "direct"]
    assert payload["results"] == []


@patch("app.fetcher.PROVIDER_API_KEYS", {"firecrawl": "fake-key"})
@patch("app.fetcher.fetch_with_firecrawl", new_callable=AsyncMock)
@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_cloak_failure_falls_through_to_firecrawl(mock_cloak, mock_firecrawl, client):
    # Cloak blows up mid-fetch (e.g. Chromium crash, network reset).
    # The chain must continue — firecrawl provides the answer.
    mock_cloak.side_effect = RuntimeError("cloak_worker exit 1: chromium crashed")
    mock_firecrawl.return_value = SIMPLE_HTML

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com", "provider_order": "cloak,firecrawl"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "firecrawl"
    mock_cloak.assert_awaited_once()
    mock_firecrawl.assert_awaited_once()


def test_cloak_is_a_valid_provider(client):
    with patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock) as mock_cloak:
        mock_cloak.return_value = (SIMPLE_HTML, {"status": 200, "redirect_history": None})
        resp = client.get(
            "/api/v1/content",
            params={"urls": "https://example.com", "provider_order": "cloak"},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert "error" not in payload


@patch("app.fetcher.fetch_with_cloak", new_callable=AsyncMock)
def test_last_provider_block_page_returns_error(mock_cloak, client):
    mock_cloak.return_value = (
        "<html><body>" + "x" * 300 + '<script src="https://js.hcaptcha.com/1/api.js"></script></body></html>',
        {"status": 200, "redirect_history": None},
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.coches.net/search/", "provider_order": "cloak"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "error"
    assert result["html"] is None
