import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import PlainTextResponse

from app import asset_fetcher, cloudflare_fetcher, firecrawl_fetcher, twitter_fetcher, youtube_fetcher
import asyncio

from app.auth import verify_token
from app.cache import cache_info, cache_size_bytes, clear_cache
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

VALID_PROVIDERS = {"scrapling", "cloudflare", "firecrawl"}
VALID_WAIT_UNTIL = {"networkidle"}

_CACHE_PARAM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*h\s*$", re.IGNORECASE)


def _parse_cache_param(value: str | None) -> float | None:
    """Parse a `cache=<N>h` query value into TTL hours. Returns None for absent/empty."""
    if value is None or not value.strip():
        return None
    match = _CACHE_PARAM_RE.match(value)
    if not match:
        raise ValueError(f"Invalid cache format: {value!r}. Expected '<N>h' (e.g. '1h', '24h').")
    hours = float(match.group(1))
    if hours <= 0:
        raise ValueError(f"Cache TTL must be > 0, got {value!r}.")
    return hours


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
    provider_order: str = Query("scrapling,cloudflare,firecrawl", description="Comma-separated provider order"),
    scroll_full: bool = Query(False, description="Scroll full page to trigger lazy-loaded content"),
    wait_until: str | None = Query(None, description="Scrapling provider only. Supports: networkidle"),
    wait_for_selector: str | None = Query(None, description="Scrapling provider only. Wait for CSS selector before reading HTML"),
    cache: str | None = Query(None, description="Opt-in cache TTL, e.g. '1h', '24h'. Absent = no cache."),
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
            "error": f"Invalid providers: {', '.join(invalid)}. Valid: scrapling, cloudflare, firecrawl",
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

    try:
        cache_ttl_hours = _parse_cache_param(cache)
    except ValueError as exc:
        return {"error": str(exc), "results": []}

    results = await fetch_urls(
        urls,
        no_style=no_style,
        no_script=no_script,
        provider_order=providers,
        scroll_full=scroll_full,
        wait_until=normalized_wait_until,
        wait_for_selector=wait_for_selector,
        cache_ttl_hours=cache_ttl_hours,
    )
    return {"results": results}


@app.get("/api/v1/cache")
async def get_cache(
    _token: str = Depends(verify_token),
):
    info = await asyncio.to_thread(cache_info)
    return info


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
