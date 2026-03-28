from fastapi import Depends, FastAPI, Query

from app.auth import verify_token
from app.fetcher import fetch_urls

app = FastAPI(title="Scrapi", version="1.0.0")

MAX_URLS_PER_REQUEST = 10


@app.get("/api/v1/content")
async def get_content(
    urls: list[str] = Query(..., description="List of URLs to fetch"),
    no_style: bool = Query(False, description="Remove all inline style attributes"),
    _token: str = Depends(verify_token),
):
    if len(urls) > MAX_URLS_PER_REQUEST:
        return {
            "error": f"Maximum {MAX_URLS_PER_REQUEST} URLs per request",
            "results": [],
        }

    results = await fetch_urls(urls, no_style=no_style)
    return {"results": results}
