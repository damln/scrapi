from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app import asset_fetcher, config, firecrawl_fetcher, twitter_fetcher, youtube_fetcher
from app.action_runner import ActionError, ActionRequest, run_action
from app.agent_docs import render_agent_markdown
from app.auth import verify_token
from app.fetcher import DEFAULT_PROVIDER_ORDER, fetch_urls
from app.pdf_renderer import PdfRenderError, PdfRenderRequest, PdfRenderResult, render_export
from app.proxy_profiles import ProxyProfileError, available_proxy_profiles, resolve_proxy_profile
from app.status import get_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.API_TOKEN:
        raise RuntimeError("SCRAPI_API_TOKEN must be set to serve the HTTP API (the CLI does not need it)")
    asset_fetcher.init_client()
    firecrawl_fetcher.init_client()
    twitter_fetcher.init_client()
    youtube_fetcher.init_client()
    yield
    await asset_fetcher.close_client()
    await firecrawl_fetcher.close_client()
    await twitter_fetcher.close_client()
    await youtube_fetcher.close_client()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

MAX_URLS_PER_REQUEST = 10

VALID_PROVIDERS = set(DEFAULT_PROVIDER_ORDER)
VALID_WAIT_UNTIL = {"domcontentloaded", "load", "networkidle"}

ROOT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scrapi</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon.png">
  <style>
    * {
      box-sizing: border-box;
    }

    html,
    body {
      width: 100%;
      min-height: 100%;
      margin: 0;
      overflow: hidden;
      background: #171a19;
    }

    body {
      min-height: 100vh;
      background:
        radial-gradient(120% 90% at 12% 8%, #2e4a3d 0%, rgba(46, 74, 61, 0) 55%),
        radial-gradient(110% 85% at 88% 15%, #3b3450 0%, rgba(59, 52, 80, 0) 55%),
        radial-gradient(100% 95% at 70% 95%, #1e3a45 0%, rgba(30, 58, 69, 0) 60%),
        #171a19;
    }
  </style>
</head>
<body>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return ROOT_HTML


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"


@app.get("/status")
async def status(
    proxy_profile: str = Query("current", description="Proxy profile to check: current, direct, or env-defined"),
):
    return await get_status(proxy_profile)


@app.get("/api/v1/status")
async def api_status(
    proxy_profile: str = Query("current", description="Proxy profile to check: current, direct, or env-defined"),
):
    return await get_status(proxy_profile)


@app.get("/api/v1/content")
async def get_content(
    urls: list[str] = Query(..., description="List of URLs to fetch"),
    no_style: bool = Query(False, description="Remove all inline style attributes"),
    no_script: bool = Query(False, description="Remove all inline script tags"),
    provider_order: str = Query(",".join(DEFAULT_PROVIDER_ORDER), description="Comma-separated provider order"),
    scroll_full: bool = Query(
        False,
        description="Scroll full page to trigger lazy-loaded content. Supported by cloak; no-op for firecrawl.",
    ),
    wait_until: str | None = Query(None, description="Cloak only. Supports: domcontentloaded, load, networkidle"),
    wait_for_selector: str | None = Query(None, description="Cloak only. Wait for CSS selector before reading HTML"),
    proxy_profile: str = Query(
        "current",
        description="Cloak only. Named proxy profile: current, direct, or an env-defined profile.",
    ),
    _token: str = Depends(verify_token),
):
    if len(urls) > MAX_URLS_PER_REQUEST:
        return {
            "error": f"Maximum {MAX_URLS_PER_REQUEST} URLs per request",
            "results": [],
        }

    providers = [p.strip() for p in provider_order.split(",") if p.strip()]
    invalid = [p for p in providers if p not in VALID_PROVIDERS]
    if invalid:
        return {
            "error": f"Invalid providers: {', '.join(invalid)}. Valid: cloak, firecrawl",
            "results": [],
        }

    normalized_wait_until = None
    if wait_until is not None:
        candidate = wait_until.strip().lower()
        if candidate and candidate not in VALID_WAIT_UNTIL:
            return {
                "error": f"Invalid wait_until: {wait_until!r}. Valid: domcontentloaded, load, networkidle",
                "results": [],
            }
        normalized_wait_until = candidate or None

    wait_for_selector = (wait_for_selector or "").strip() or None
    normalized_proxy_profile = proxy_profile.strip() or "current"
    try:
        resolve_proxy_profile(normalized_proxy_profile)
    except ProxyProfileError as exc:
        profiles = ["current", "direct"]
        with suppress(ProxyProfileError):
            profiles = available_proxy_profiles()
        return {
            "error": str(exc),
            "profiles": profiles,
            "results": [],
        }

    results = await fetch_urls(
        urls,
        no_style=no_style,
        no_script=no_script,
        provider_order=providers,
        scroll_full=scroll_full,
        wait_until=normalized_wait_until,
        wait_for_selector=wait_for_selector,
        proxy_profile=normalized_proxy_profile,
    )
    return {"results": results}


@app.get("/api/v1/agent", response_class=PlainTextResponse)
async def get_agent():
    return render_agent_markdown(app)


@app.get("/api/v1/asset")
async def get_asset(
    url: str = Query(..., description="Asset URL to download"),
    output_format: str | None = Query(None, description="Image format and quality, e.g. 'JPG,98' or 'WEBP,85'"),
    max_width: int | None = Query(None, ge=1, description="Max width in pixels (aspect ratio preserved)"),
    max_height: int | None = Query(None, ge=1, description="Max height in pixels (aspect ratio preserved)"),
    _token: str = Depends(verify_token),
):
    return await asset_fetcher.fetch_and_process_asset(url, output_format, max_width, max_height)


def _export_response(result: PdfRenderResult) -> Response:
    headers = {"Content-Disposition": f'inline; filename="scrapi.{result.extension}"'}
    if result.final_url:
        headers["X-Scrapi-Final-Url"] = result.final_url
    if result.http_status is not None:
        headers["X-Scrapi-Http-Status"] = str(result.http_status)
    return Response(
        content=result.data,
        media_type=result.content_type,
        headers=headers,
    )


async def _render_export_response(request: PdfRenderRequest):
    try:
        result = await render_export(request)
    except PdfRenderError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": str(exc),
            },
        )

    return _export_response(result)


@app.post("/api/v1/export")
async def render_export_endpoint(
    request: PdfRenderRequest,
    _token: str = Depends(verify_token),
):
    return await _render_export_response(request)


# ── Actions: replay an inline session into a stealth browser and act ──
# Stateless: the caller passes the browser identity (cookies + UA) inline in
# the request body. Nothing is stored server-side. Gated by the API token.


@app.post("/api/v1/actions")
async def run_action_endpoint(
    request: ActionRequest,
    _token: str = Depends(verify_token),
):
    try:
        result = await run_action(request)
    except ActionError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": "error", "error": str(exc)},
        )
    return {
        "status": result.status,
        "result": result.result,
        "log": result.log,
        "final_url": result.final_url,
        "screenshot_base64": result.screenshot_base64,
    }
