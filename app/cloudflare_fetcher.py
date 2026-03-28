import httpx

from app.config import CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_KEY, CLOUDFLARE_TIMEOUT_SECONDS

_client: httpx.AsyncClient | None = None

_SCROLL_SCRIPT = """
(async () => {
    const stepPx = 800;
    const delayMs = 400;
    const maxIter = 40;
    let prev = document.body.scrollHeight;
    for (let i = 0; i < maxIter; i++) {
        window.scrollBy(0, stepPx);
        await new Promise(r => setTimeout(r, delayMs));
        const reached = window.pageYOffset + window.innerHeight >= document.body.scrollHeight - 50;
        const curr = document.body.scrollHeight;
        if (reached && curr === prev) break;
        prev = curr;
    }
    await new Promise(r => setTimeout(r, 1500));
    window.scrollTo(0, 0);
})();
"""


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=CLOUDFLARE_TIMEOUT_SECONDS)


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def fetch_with_cloudflare(url: str, scroll_full: bool = False) -> str:
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

    if scroll_full:
        payload["addScriptTag"] = [{"content": _SCROLL_SCRIPT}]
        payload["waitForTimeout"] = 20500

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
