from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.proxy_profiles import ProxyProfileError, available_proxy_profiles, resolve_proxy_profile

PROXY_CHECK_URL = "https://api.ipify.org"
PROXY_CHECK_TIMEOUT_S = 10


def _redact_proxy_url(proxy_url: str) -> str:
    parsed = urlsplit(proxy_url)
    if not parsed.hostname:
        return proxy_url

    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if parsed.username or parsed.password:
        host = f"[redacted]@{host}"

    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


async def get_status(proxy_profile: str = "current") -> dict:
    normalized_proxy_profile = proxy_profile.strip() or "current"
    try:
        proxy_url = resolve_proxy_profile(normalized_proxy_profile)
        profiles = available_proxy_profiles()
    except ProxyProfileError as exc:
        return {
            "status": "degraded",
            "proxy": {
                "profile": normalized_proxy_profile,
                "available_profiles": ["current", "direct"],
                "configured": False,
                "url": None,
                "check_url": PROXY_CHECK_URL,
                "ok": False,
                "ip": None,
                "error": str(exc),
                "elapsed_ms": None,
            },
        }

    status: dict[str, Any] = {
        "status": "ok",
        "proxy": {
            "profile": normalized_proxy_profile,
            "available_profiles": profiles,
            "configured": bool(proxy_url),
            "url": _redact_proxy_url(proxy_url) if proxy_url else None,
            "check_url": PROXY_CHECK_URL,
            "ok": False,
            "ip": None,
            "error": None,
            "elapsed_ms": None,
        },
    }

    if not proxy_url:
        # No proxy configured means the profile resolves to a direct
        # connection — a valid default, not a degraded state.
        status["proxy"]["ok"] = True
        status["proxy"]["error"] = None
        if normalized_proxy_profile != "direct":
            status["proxy"]["note"] = "PROXY_URL is not set; fetches run direct (no proxy)"
        return status

    started = monotonic()
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=httpx.Timeout(PROXY_CHECK_TIMEOUT_S),
            follow_redirects=True,
        ) as client:
            resp = await client.get(PROXY_CHECK_URL)
            resp.raise_for_status()
    except Exception as exc:
        status["status"] = "degraded"
        status["proxy"]["error"] = str(exc)
    else:
        status["proxy"]["ok"] = True
        status["proxy"]["ip"] = resp.text.strip()
    finally:
        status["proxy"]["elapsed_ms"] = round((monotonic() - started) * 1000)

    return status
