from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.responses import PlainTextResponse

from app import asset_fetcher, cloudflare_fetcher, firecrawl_fetcher, twitter_fetcher, youtube_fetcher
import asyncio

from app.auth import verify_token
from app.cache import cache_size_bytes, clear_cache
from app.fetcher import fetch_urls


@asynccontextmanager
async def lifespan(app: FastAPI):
    asset_fetcher.init_client()
    cloudflare_fetcher.init_client()
    firecrawl_fetcher.init_client()
    twitter_fetcher.init_client()
    youtube_fetcher.init_client()
    yield
    await asset_fetcher.close_client()
    await cloudflare_fetcher.close_client()
    await firecrawl_fetcher.close_client()
    await twitter_fetcher.close_client()
    await youtube_fetcher.close_client()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

MAX_URLS_PER_REQUEST = 10

VALID_PROVIDERS = {"raw", "cloudflare", "firecrawl"}


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
    provider_order: str = Query("raw,cloudflare,firecrawl", description="Comma-separated provider order"),
    scroll_full: bool = Query(False, description="Scroll full page to trigger lazy-loaded content"),
    force_fetch: bool = Query(False, description="Bypass cache and force a fresh fetch"),
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
            "error": f"Invalid providers: {', '.join(invalid)}. Valid: raw, cloudflare, firecrawl",
            "results": [],
        }

    results = await fetch_urls(urls, no_style=no_style, no_script=no_script, provider_order=providers, scroll_full=scroll_full, force_fetch=force_fetch)
    return {"results": results}


@app.delete("/api/v1/cache")
async def delete_cache(
    _token: str = Depends(verify_token),
):
    size_before = await asyncio.to_thread(cache_size_bytes)
    entries_removed = await asyncio.to_thread(clear_cache)
    return {
        "status": "ok",
        "entries_removed": entries_removed,
        "size_freed_mb": round(size_before / (1024 * 1024), 2),
    }


@app.get("/api/v1/asset")
async def get_asset(
    url: str = Query(..., description="Asset URL to download"),
    output_format: str | None = Query(None, description="Image format and quality, e.g. 'JPG,98' or 'WEBP,85'"),
    max_width: int | None = Query(None, ge=1, description="Max width in pixels (aspect ratio preserved)"),
    max_height: int | None = Query(None, ge=1, description="Max height in pixels (aspect ratio preserved)"),
    _token: str = Depends(verify_token),
):
    return await asset_fetcher.fetch_and_process_asset(url, output_format, max_width, max_height)
