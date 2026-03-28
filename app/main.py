from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.responses import PlainTextResponse

from app import cloudflare_fetcher, firecrawl_fetcher
from app.auth import verify_token
from app.fetcher import fetch_urls


@asynccontextmanager
async def lifespan(app: FastAPI):
    cloudflare_fetcher.init_client()
    firecrawl_fetcher.init_client()
    yield
    await cloudflare_fetcher.close_client()
    await firecrawl_fetcher.close_client()


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

    results = await fetch_urls(urls, no_style=no_style, no_script=no_script, provider_order=providers, scroll_full=scroll_full)
    return {"results": results}
