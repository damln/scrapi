import httpx

from app.config import FIRECRAWL_API_KEY, FIRECRAWL_BASE_URL, FIRECRAWL_TIMEOUT_SECONDS


async def fetch_with_firecrawl(url: str) -> str:
    """Fetch HTML content via Firecrawl API.

    Raises on any failure (HTTP error, missing content, invalid response).
    """
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["rawHtml"],
        "onlyMainContent": False,
    }

    async with httpx.AsyncClient(timeout=FIRECRAWL_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{FIRECRAWL_BASE_URL}/scrape", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    if not data.get("success"):
        raise RuntimeError(f"Firecrawl API error: {data}")

    html = data.get("data", {}).get("rawHtml", "")
    if not html:
        raise RuntimeError("Firecrawl returned empty content")

    return html
