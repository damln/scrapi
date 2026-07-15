from unittest.mock import AsyncMock, patch

from app.agent_examples import EXAMPLE_PAGE_URL
from tests.conftest import AUTH_HEADER

PDF_BYTES = b"%PDF-1.4\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n"
TARGET_URL = EXAMPLE_PAGE_URL
RAW_HTML = "<!doctype html><html><body><main>Report</main></body></html>"


def test_export_requires_auth(client):
    resp = client.post("/api/v1/export", json={"url": TARGET_URL})
    assert resp.status_code in (401, 403)


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_defaults_to_binary_pdf(mock_render, client):
    from app.pdf_renderer import PdfRenderResult

    mock_render.return_value = PdfRenderResult(
        data=PDF_BYTES,
        content_type="application/pdf",
        extension="pdf",
        final_url=TARGET_URL,
        http_status=200,
    )

    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["x-scrapi-final-url"] == TARGET_URL
    assert resp.headers["x-scrapi-http-status"] == "200"
    assert resp.headers["content-disposition"] == 'inline; filename="scrapi.pdf"'
    assert resp.content == PDF_BYTES

    request = mock_render.await_args.args[0]
    assert request.type == "pdf"
    assert request.page.width == "10in"
    assert request.page.height == "7.5in"
    assert request.page.print_background is True
    assert request.page.rasterize is True
    assert request.page.raster_quality == "best"
    assert request.media == "screen"


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_returns_binary_png(mock_render, client):
    from app.pdf_renderer import PdfRenderResult

    mock_render.return_value = PdfRenderResult(
        data=PNG_BYTES,
        content_type="image/png",
        extension="png",
        final_url=TARGET_URL,
        http_status=200,
    )

    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL, "type": "png"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["content-disposition"] == 'inline; filename="scrapi.png"'
    assert resp.content == PNG_BYTES

    request = mock_render.await_args.args[0]
    assert request.type == "png"
    assert request.png.full_page is True


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_accepts_raw_html(mock_render, client):
    from app.pdf_renderer import PdfRenderResult

    mock_render.return_value = PdfRenderResult(
        data=PDF_BYTES,
        content_type="application/pdf",
        extension="pdf",
        final_url="about:blank",
        http_status=None,
    )

    resp = client.post(
        "/api/v1/export",
        json={"html": RAW_HTML},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    request = mock_render.await_args.args[0]
    assert request.url is None
    assert request.html == RAW_HTML
    assert request.type == "pdf"


def test_export_rejects_url_and_html_together(client):
    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL, "html": RAW_HTML},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_requires_url_or_html(client):
    resp = client.post(
        "/api/v1/export",
        json={"type": "pdf"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_headers_with_raw_html(client):
    resp = client.post(
        "/api/v1/export",
        json={"html": RAW_HTML, "headers": {"Authorization": "Bearer private-page-token"}},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_pdf_route_is_not_available(client):
    resp = client.post(
        "/api/v1/pdf",
        json={"url": TARGET_URL},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 404


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_accepts_render_options(mock_render, client):
    from app.pdf_renderer import PdfRenderResult

    mock_render.return_value = PdfRenderResult(
        data=PDF_BYTES,
        content_type="application/pdf",
        extension="pdf",
        final_url=None,
        http_status=None,
    )

    resp = client.post(
        "/api/v1/export",
        json={
            "url": TARGET_URL,
            "type": "pdf",
            "headers": {"Authorization": "Bearer private-page-token"},
            "header_scope": "same_origin",
            "basic_auth": {"username": "user", "password": "pass"},
            "viewport": {"width": 1200, "height": 900},
            "media": "print",
            "page": {
                "width": "8.5in",
                "height": "11in",
                "margin": {"top": "0.25in", "right": "0", "bottom": "0.25in", "left": "0"},
                "scale": 0.9,
                "print_background": False,
                "rasterize": True,
                "raster_quality": "optimized",
            },
            "png": {
                "full_page": False,
                "omit_background": True,
                "scale": "css",
            },
            "wait": {
                "goto": "domcontentloaded",
                "selector": "main",
                "selector_required": False,
                "selector_timeout_ms": 5000,
                "ready_expression": "() => window.READY === true",
                "ready_expression_required": False,
                "ready_expression_timeout_ms": 5000,
                "scroll_to_end": True,
                "scroll_step_px": 900,
                "scroll_delay_ms": 50,
                "scroll_settle_ms": 1500,
                "timeout_ms": 45000,
            },
            "remove": {
                "css": [".cookie-banner", "[data-pdf-hidden='true']"],
                "xpath": ["//aside[contains(@class, 'sidebar')]"],
            },
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    request = mock_render.await_args.args[0]
    assert request.type == "pdf"
    assert request.headers["Authorization"] == "Bearer private-page-token"
    assert request.basic_auth.username == "user"
    assert request.viewport.width == 1200
    assert request.media == "print"
    assert request.page.width == "8.5in"
    assert request.page.print_background is False
    assert request.page.rasterize is True
    assert request.page.raster_quality == "optimized"
    assert request.wait.selector == "main"
    assert request.wait.selector_required is False
    assert request.wait.selector_timeout_ms == 5000
    assert request.wait.ready_expression == "() => window.READY === true"
    assert request.wait.ready_expression_required is False
    assert request.wait.ready_expression_timeout_ms == 5000
    assert request.wait.scroll_to_end is True
    assert request.wait.scroll_step_px == 900
    assert request.wait.scroll_delay_ms == 50
    assert request.wait.scroll_settle_ms == 1500
    assert request.png.full_page is False
    assert request.png.omit_background is True
    assert request.png.scale == "css"
    assert request.remove.css == [".cookie-banner", "[data-pdf-hidden='true']"]
    assert request.remove.xpath == ["//aside[contains(@class, 'sidebar')]"]


def test_export_accepts_pdf_page_format_without_default_dimensions(client):
    with patch("app.main.render_export", new_callable=AsyncMock) as mock_render:
        from app.pdf_renderer import PdfRenderResult

        mock_render.return_value = PdfRenderResult(
            data=PDF_BYTES,
            content_type="application/pdf",
            extension="pdf",
            final_url=None,
            http_status=None,
        )

        resp = client.post(
            "/api/v1/export",
            json={
                "url": TARGET_URL,
                "page": {"format": "A4"},
            },
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    request = mock_render.await_args.args[0]
    assert request.page.format == "A4"
    assert request.page.width is None
    assert request.page.height is None


def test_export_rejects_pdf_page_format_with_dimensions(client):
    resp = client.post(
        "/api/v1/export",
        json={
            "url": TARGET_URL,
            "page": {"format": "A4", "width": "10in", "height": "7.5in"},
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_invalid_dimensions(client):
    resp = client.post(
        "/api/v1/export",
        json={
            "url": TARGET_URL,
            "page": {"width": "10banana", "height": "7.5in"},
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_invalid_type(client):
    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL, "type": "jpeg"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_legacy_format_field(client):
    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL, "format": "png"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_invalid_header(client):
    resp = client.post(
        "/api/v1/export",
        json={
            "url": TARGET_URL,
            "headers": {"Host": "target.invalid"},
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


def test_export_rejects_blank_remove_selector(client):
    resp = client.post(
        "/api/v1/export",
        json={
            "url": TARGET_URL,
            "remove": {"css": [""]},
        },
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_renderer_failure_returns_json_error(mock_render, client):
    from app.pdf_renderer import PdfRenderError

    mock_render.side_effect = PdfRenderError("Target returned HTTP 500", status_code=502)

    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 502
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["status"] == "error"
    assert resp.json()["error"] == "Target returned HTTP 500"


@patch("app.main.render_export", new_callable=AsyncMock)
def test_export_renderer_timeout_returns_json_error(mock_render, client):
    from app.pdf_renderer import PdfRenderError

    mock_render.side_effect = PdfRenderError("Export render timeout (45000ms)", status_code=504)

    resp = client.post(
        "/api/v1/export",
        json={"url": TARGET_URL},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 504
    assert resp.json()["status"] == "error"
