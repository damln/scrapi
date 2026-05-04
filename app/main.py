from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import PlainTextResponse

from app import asset_fetcher, cloudflare_fetcher, diagnostics, firecrawl_fetcher, twitter_fetcher, youtube_fetcher
import asyncio

from app.auth import verify_token
from app.fetcher import fetch_urls


@asynccontextmanager
async def lifespan(app: FastAPI):
    asset_fetcher.init_client()
    cloudflare_fetcher.init_client()
    diagnostics.init_client()
    firecrawl_fetcher.init_client()
    twitter_fetcher.init_client()
    youtube_fetcher.init_client()
    # Pre-warm the egress IP cache in the background so the first
    # /api/v1/content call doesn't pay the discovery latency.
    asyncio.create_task(diagnostics.get_egress_ip())
    yield
    await asset_fetcher.close_client()
    await cloudflare_fetcher.close_client()
    await diagnostics.close_client()
    await firecrawl_fetcher.close_client()
    await twitter_fetcher.close_client()
    await youtube_fetcher.close_client()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

MAX_URLS_PER_REQUEST = 10

VALID_PROVIDERS = {"obscura", "scrapling", "cloudflare", "firecrawl"}
VALID_WAIT_UNTIL = {"networkidle"}


@app.get("/", response_class=PlainTextResponse)
async def root():
    return "ok"


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"


@app.get("/api/v1/content")
async def get_content(
    urls: list[str] = Query(..., description="List of URLs to fetch"),
    no_style: bool = Query(False, description="Remove all inline style attributes"),
    no_script: bool = Query(False, description="Remove all inline script tags"),
    provider_order: str = Query("obscura,scrapling,cloudflare,firecrawl", description="Comma-separated provider order"),
    scroll_full: bool = Query(False, description="Scroll full page to trigger lazy-loaded content. Supported by scrapling and cloudflare; no-op for obscura and firecrawl."),
    wait_until: str | None = Query(None, description="Obscura/scrapling only. Supports: networkidle"),
    wait_for_selector: str | None = Query(None, description="Obscura/scrapling only. Wait for CSS selector before reading HTML"),
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
            "error": f"Invalid providers: {', '.join(invalid)}. Valid: obscura, scrapling, cloudflare, firecrawl",
            "results": [],
        }

    normalized_wait_until = None
    if wait_until is not None:
        candidate = wait_until.strip().lower()
        if candidate and candidate not in VALID_WAIT_UNTIL:
            return {
                "error": f"Invalid wait_until: {wait_until!r}. Valid: networkidle",
                "results": [],
            }
        normalized_wait_until = candidate or None

    wait_for_selector = (wait_for_selector or "").strip() or None

    results = await fetch_urls(
        urls,
        no_style=no_style,
        no_script=no_script,
        provider_order=providers,
        scroll_full=scroll_full,
        wait_until=normalized_wait_until,
        wait_for_selector=wait_for_selector,
    )
    return {"results": results}


@app.get("/api/v1/agent", response_class=PlainTextResponse)
async def get_agent():
    """Public discovery endpoint: raw AGENTS.md for agents to self-describe the API."""
    agents_path = Path(__file__).resolve().parent.parent / "AGENTS.md"
    return agents_path.read_text(encoding="utf-8")


@app.get("/api/v1/asset")
async def get_asset(
    url: str = Query(..., description="Asset URL to download"),
    output_format: str | None = Query(None, description="Image format and quality, e.g. 'JPG,98' or 'WEBP,85'"),
    max_width: int | None = Query(None, ge=1, description="Max width in pixels (aspect ratio preserved)"),
    max_height: int | None = Query(None, ge=1, description="Max height in pixels (aspect ratio preserved)"),
    _token: str = Depends(verify_token),
):
    return await asset_fetcher.fetch_and_process_asset(url, output_format, max_width, max_height)
