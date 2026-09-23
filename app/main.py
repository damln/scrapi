import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app import asset_fetcher, config
from app.action_runner import ActionError, ActionRequest, run_action
from app.agent_docs import render_agent_markdown
from app.auth import verify_token
from app.browser_capture import (
    BrowserCaptureApiRequest,
    BrowserCaptureError,
    build_capture_archive,
    capture_browser,
)
from app.fetch_clients import fetch_clients
from app.fetcher import DEFAULT_PROVIDER_ORDER, fetch_urls
from app.image_jobs import ImageJobs
from app.image_routes import router as image_router
from app.pdf_renderer import PdfRenderError, PdfRenderRequest, PdfRenderResult, render_export
from app.proxy_profiles import ProxyProfileError, available_proxy_profiles, resolve_proxy_profile
from app.screenshot import build_screenshot_archive, parse_viewports
from app.status import get_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.API_TOKEN:
        raise RuntimeError("SCRAPI_API_TOKEN must be set to serve the HTTP API (the CLI does not need it)")
    async with fetch_clients():
        app.state.image_jobs = ImageJobs()
        app.state.image_jobs.start()
        try:
            yield
        finally:
            await app.state.image_jobs.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(image_router)
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


@app.post("/api/v1/capture")
async def capture_browser_endpoint(
    request: BrowserCaptureApiRequest,
    _token: str = Depends(verify_token),
):
    """Return a stateless ZIP containing capture metadata and requested evidence."""
    try:
        proxy_url = resolve_proxy_profile(request.proxy_profile)
    except ProxyProfileError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(exc)})

    root = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="scrapi-capture-api-"))
    evidence = root / "evidence"
    archive = root / "scrapi-capture.zip"
    try:
        result = await capture_browser(request.to_capture_request(str(evidence), proxy_url))
        portable = await asyncio.to_thread(build_capture_archive, result, evidence, archive)
    except BrowserCaptureError as exc:
        await asyncio.to_thread(shutil.rmtree, root, True)
        return JSONResponse(status_code=502, content={"status": "error", "error": str(exc)})
    except Exception:
        await asyncio.to_thread(shutil.rmtree, root, True)
        raise

    headers = {
        "X-Scrapi-Capture-Status": portable["status"],
        "X-Scrapi-Http-Status": str(portable.get("http_status") or ""),
    }
    return FileResponse(
        archive,
        media_type="application/zip",
        filename="scrapi-capture.zip",
        headers=headers,
        background=BackgroundTask(shutil.rmtree, root, True),
    )


@app.get("/api/v1/screenshot")
async def screenshot_endpoint(
    url: str = Query(..., description="Absolute HTTP(S) page URL"),
    viewport: Annotated[
        list[str] | None,
        Query(description="Repeat desktop, mobile, or WIDTHxHEIGHT to capture multiple responsive sizes"),
    ] = None,
    full_page: bool = Query(True, description="Capture the full page instead of the visible viewport"),
    quality: int = Query(98, ge=0, le=100, description="JPEG quality"),
    render_scale: int = Query(
        1,
        ge=1,
        le=2,
        description="Render at 2x before downsampling to the requested output dimensions",
    ),
    max_page_height: int = Query(
        20_000,
        ge=240,
        le=50_000,
        description="Maximum full-page screenshot height in CSS pixels",
    ),
    scroll_full: bool = Query(False, description="Scroll before capture to load lazy or infinite content"),
    max_scroll_steps: int = Query(60, ge=1, le=500, description="Maximum scroll steps before capture"),
    wait_for_selector: str | None = Query(None, description="Wait for a CSS selector before capture"),
    proxy_profile: str = Query("current", description="Named proxy profile"),
    _token: str = Depends(verify_token),
):
    try:
        url = BrowserCaptureApiRequest.absolute_http_url(url)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"status": "error", "error": str(exc)})

    try:
        viewports = parse_viewports(viewport)
        proxy_url = resolve_proxy_profile(proxy_profile)
    except (ValueError, ProxyProfileError) as exc:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(exc)})

    root = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="scrapi-screenshot-api-"))
    archive = root / "scrapi-screenshots.zip"
    captures = []
    try:
        for width, height in viewports:
            evidence = root / f"{width}x{height}"
            request = BrowserCaptureApiRequest.model_validate(
                {
                    "url": url,
                    "width": width,
                    "height": height,
                    "proxy_profile": proxy_profile,
                    "wait_for_selector": (wait_for_selector or "").strip() or None,
                    "scroll_full": scroll_full,
                    "max_scroll_steps": max_scroll_steps,
                    "screenshot": "full" if full_page else "viewport",
                    "screenshot_format": "jpeg",
                    "screenshot_quality": quality,
                    "render_scale": render_scale,
                    "max_screenshot_height": max_page_height,
                    "html": False,
                    "har": False,
                }
            )
            captures.append(await capture_browser(request.to_capture_request(str(evidence), proxy_url)))

        if len(captures) == 1:
            result = captures[0]
            screenshot = Path(result["files"]["screenshot"])
            headers = {
                "X-Scrapi-Final-Url": result["url"],
                "X-Scrapi-Http-Status": str(result.get("http_status") or ""),
                "X-Scrapi-Screenshot-Capped": str(bool(result["screenshot"]["capped"])).lower(),
            }
            return FileResponse(
                screenshot,
                media_type="image/jpeg",
                filename=f"screenshot-{viewports[0][0]}x{viewports[0][1]}.jpg",
                content_disposition_type="inline",
                headers=headers,
                background=BackgroundTask(shutil.rmtree, root, True),
            )

        await asyncio.to_thread(build_screenshot_archive, captures, archive)
    except BrowserCaptureError as exc:
        await asyncio.to_thread(shutil.rmtree, root, True)
        return JSONResponse(status_code=502, content={"status": "error", "error": str(exc)})
    except Exception:
        await asyncio.to_thread(shutil.rmtree, root, True)
        raise

    return FileResponse(
        archive,
        media_type="application/zip",
        filename="scrapi-screenshots.zip",
        background=BackgroundTask(shutil.rmtree, root, True),
    )


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
