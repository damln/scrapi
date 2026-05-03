"""Egress IP discovery + sibling-HTTP-metadata helper.

Two diagnostics that don't fit a single provider:

1. **Egress IP** — the public IP scrapi (and httpx-based providers) appear
   from. Useful when chasing "why is this site blocking us" or verifying
   the SOCKS5 residential proxy is engaged. Discovered once via
   api.ipify.org and cached for the lifetime of the process. Not refreshed
   — restart the container to re-discover.

2. **Sibling HTTP metadata** — for providers whose underlying tool does
   NOT expose response status/headers/redirects (Obscura's CLI fits this:
   `--dump html` only emits the body), we make a parallel httpx GET to
   the same URL and report what *that* request received. Marked with
   `source: "sibling-httpx"` so consumers know it's not the provider's
   own response — TLS fingerprint, cookies, and CDN routing may differ.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_egress_ip: str | None = None
_egress_ip_lock = asyncio.Lock()


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        follow_redirects=True,
        headers={"User-Agent": "scrapi-diagnostics/1.0"},
    )


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_egress_ip() -> str | None:
    """Return the cached egress IP, discovering it on first call.

    None on persistent failure — never raises. The lock ensures concurrent
    callers don't fire N parallel discovery requests during the warm-up.
    """
    global _egress_ip
    if _egress_ip is not None:
        return _egress_ip
    async with _egress_ip_lock:
        if _egress_ip is not None:
            return _egress_ip
        assert _client is not None, "diagnostics httpx client not initialized"
        try:
            resp = await _client.get("https://api.ipify.org/?format=json")
            resp.raise_for_status()
            ip = resp.json().get("ip")
            if isinstance(ip, str) and ip:
                _egress_ip = ip
                logger.info("Discovered egress IP: %s", ip)
                return ip
        except Exception as exc:
            logger.warning("Egress IP discovery failed: %s", exc)
    return None


async def fetch_sibling_http_metadata(url: str) -> dict:
    """Fetch `url` via httpx to capture status + response headers.

    Used by providers (notably Obscura) whose underlying tool doesn't
    surface HTTP metadata. Best-effort — returns an empty dict on
    failure so the caller can continue rather than fail the fetch.
    The `source` field marks the result as not-from-the-provider.
    """
    assert _client is not None, "diagnostics httpx client not initialized"
    try:
        resp = await _client.get(url)
    except Exception as exc:
        logger.warning("Sibling HTTP metadata fetch failed for %s: %s", url, exc)
        return {}

    history = []
    for r in resp.history:
        h = {"status": r.status_code, "url": str(r.url), "headers": dict(r.headers)}
        history.append(h)

    return {
        "source": "sibling-httpx",
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "redirect_history": history or None,
    }
