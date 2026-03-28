import httpx

from app.config import CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_KEY, CLOUDFLARE_TIMEOUT_SECONDS

_client: httpx.AsyncClient | None = None


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=CLOUDFLARE_TIMEOUT_SECONDS)


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def fetch_with_cloudflare(url: str) -> str:
    """Fetch HTML content via Cloudflare Browser Rendering API.

    Raises on any failure (HTTP error, missing content, invalid response).
    """
    assert _client is not None, "Cloudflare httpx client not initialized — call init_client() first"

    base_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/browser-rendering"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "gotoOptions": {"waitUntil": "networkidle0"},
        "rejectResourceTypes": ["image"],
    }

    response = await _client.post(f"{base_url}/content", headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        errors = data.get("errors", [])
        msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
        raise RuntimeError(f"Cloudflare API error: {msg}")

    html = data.get("result", "")
    if not html:
        raise RuntimeError("Cloudflare returned empty content")

    return html
