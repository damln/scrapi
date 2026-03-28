import httpx

from app.config import FIRECRAWL_API_KEY, FIRECRAWL_BASE_URL, FIRECRAWL_TIMEOUT_SECONDS

_client: httpx.AsyncClient | None = None


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=FIRECRAWL_TIMEOUT_SECONDS)


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def fetch_with_firecrawl(url: str) -> str:
    """Fetch HTML content via Firecrawl API.

    Raises on any failure (HTTP error, missing content, invalid response).
    """
    assert _client is not None, "Firecrawl httpx client not initialized — call init_client() first"

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["rawHtml"],
        "onlyMainContent": False,
    }

    response = await _client.post(f"{FIRECRAWL_BASE_URL}/scrape", headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        raise RuntimeError(f"Firecrawl API error: {data}")

    html = data.get("data", {}).get("rawHtml", "")
    if not html:
        raise RuntimeError("Firecrawl returned empty content")

    return html
