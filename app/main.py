from fastapi import Depends, FastAPI, Query

from app.auth import verify_token
from app.fetcher import fetch_urls

app = FastAPI(title="Scrapi", version="1.0.0")

MAX_URLS_PER_REQUEST = 10


VALID_PROVIDERS = {"raw", "cloudflare", "firecrawl"}


@app.get("/api/v1/content")
async def get_content(
    urls: list[str] = Query(..., description="List of URLs to fetch"),
    no_style: bool = Query(False, description="Remove all inline style attributes"),
    provider_order: str = Query("raw,cloudflare,firecrawl", description="Comma-separated provider order"),
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

    results = await fetch_urls(urls, no_style=no_style, provider_order=providers)
    return {"results": results}
