from __future__ import annotations

import base64
import json
from dataclasses import asdict

from app.action_runner import ActionRequest, ActionResult
from app.browser_capture import BrowserCaptureApiRequest
from app.fetcher import DEFAULT_PROVIDER_ORDER, _post_process, _success
from app.pdf_renderer import PdfRenderRequest, PdfRenderResult

EXAMPLE_PAGE_URL = "https://example.com"
EXAMPLE_ASSET_URL = "https://cdn.example.com/image.png"
EXAMPLE_HTML = "<html><head><title>Example</title></head><body><main>Hello Scrapi</main></body></html>"

_EXAMPLE_SESSION = {
    "cookies": [{"name": "auth_token", "value": "...", "domain": ".x.com"}],
}


def curl_examples() -> dict[str, list[str]]:
    export_body = PdfRenderRequest.model_validate(
        {
            "url": EXAMPLE_PAGE_URL,
            "type": "pdf",
            "wait": {"selector": "main", "selector_required": False},
        }
    ).model_dump(mode="json", exclude_none=True)
    action_body = ActionRequest.model_validate(
        {
            "session": _EXAMPLE_SESSION,
            "url": "https://x.com/compose/post",
            "recipe": "x_post",
            "params": {"text": "hello", "dry_run": True},
        }
    ).model_dump(mode="json", exclude_none=True)
    capture_body = BrowserCaptureApiRequest.model_validate(
        {
            "url": EXAMPLE_PAGE_URL,
            "video": True,
            "scroll_full": True,
            "resources": "assets",
        }
    ).model_dump(mode="json", exclude_none=True)

    return {
        "GET /api/v1/content": [
            'curl -sS -G "$SCRAPI_BASE_URL/api/v1/content" \\',
            '  -H "Authorization: Bearer $SCRAPI_API_TOKEN" \\',
            f'  --data-urlencode "urls={EXAMPLE_PAGE_URL}"',
        ],
        "GET /api/v1/asset": [
            'curl -sS -G "$SCRAPI_BASE_URL/api/v1/asset" \\',
            '  -H "Authorization: Bearer $SCRAPI_API_TOKEN" \\',
            f'  --data-urlencode "url={EXAMPLE_ASSET_URL}" \\',
            '  --data-urlencode "output_format=WEBP,85"',
        ],
        "POST /api/v1/export": [
            'curl -sS -X POST "$SCRAPI_BASE_URL/api/v1/export" \\',
            '  -H "Authorization: Bearer $SCRAPI_API_TOKEN" \\',
            '  -H "Content-Type: application/json" \\',
            f"  -d '{_compact_json(export_body)}' \\",
            "  -o scrapi.pdf",
        ],
        "POST /api/v1/capture": [
            'curl -sS -X POST "$SCRAPI_BASE_URL/api/v1/capture" \\',
            '  -H "Authorization: Bearer $SCRAPI_API_TOKEN" \\',
            '  -H "Content-Type: application/json" \\',
            f"  -d '{_compact_json(capture_body)}' \\",
            "  -o scrapi-capture.zip",
        ],
        "POST /api/v1/actions": [
            'curl -sS -X POST "$SCRAPI_BASE_URL/api/v1/actions" \\',
            '  -H "Authorization: Bearer $SCRAPI_API_TOKEN" \\',
            '  -H "Content-Type: application/json" \\',
            f"  -d '{_compact_json(action_body)}'",
        ],
    }


def response_examples() -> dict[str, object]:
    html, head_meta, markdown = _post_process(EXAMPLE_HTML, EXAMPLE_PAGE_URL, no_style=False, no_script=False)
    content_result = _success(
        EXAMPLE_PAGE_URL,
        EXAMPLE_PAGE_URL,
        html,
        DEFAULT_PROVIDER_ORDER[0],
        scores={"length": len(html)},
        head_meta=head_meta,
        markdown=markdown,
        http_metadata={"status": 200, "redirect_history": None},
    )
    export_result = PdfRenderResult(
        data=b"%PDF-1.4\n%%EOF\n",
        content_type="application/pdf",
        extension="pdf",
        final_url=EXAMPLE_PAGE_URL,
        http_status=200,
    )
    action_result = ActionResult(
        status="success",
        result={"posted": False, "dry_run": True, "tweets": 1},
        log=["typed tweet 1/1", "dry_run: not publishing"],
        final_url="https://x.com/compose/post",
        screenshot_base64=None,
    )

    return {
        "GET /api/v1/content": {"results": [content_result]},
        "GET /api/v1/asset": {
            "url": EXAMPLE_ASSET_URL,
            "status": "success",
            "content_type": "image/png",
            "format": "PNG",
            "width": 1,
            "height": 1,
            "data": base64.b64encode(b"png bytes").decode("ascii"),
            "http": {"status": 200, "redirect_history": None},
        },
        "POST /api/v1/export": {
            "body": "<binary>",
            "headers": {
                "content-type": export_result.content_type,
                "content-disposition": f'inline; filename="scrapi.{export_result.extension}"',
                "x-scrapi-final-url": export_result.final_url,
                "x-scrapi-http-status": export_result.http_status,
            },
        },
        "POST /api/v1/capture": {
            "body": "<zip: result.json + requested artifacts>",
            "headers": {
                "content-type": "application/zip",
                "content-disposition": 'attachment; filename="scrapi-capture.zip"',
            },
        },
        "POST /api/v1/actions": asdict(action_result),
    }


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))
