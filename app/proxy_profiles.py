from __future__ import annotations

import json
import os
import re

PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class ProxyProfileError(ValueError):
    pass


def available_proxy_profiles(env: dict[str, str] | None = None) -> list[str]:
    return sorted(load_proxy_profiles(env).keys())


def resolve_proxy_profile(profile: str, env: dict[str, str] | None = None) -> str:
    normalized = (profile or "current").strip()
    profiles = load_proxy_profiles(env)
    if normalized not in profiles:
        valid = ", ".join(sorted(profiles))
        raise ProxyProfileError(f"Invalid proxy_profile: {profile!r}. Valid: {valid}")
    return profiles[normalized]


def load_proxy_profiles(env: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if env is None else env
    profiles = {
        "current": source.get("PROXY_URL", "").strip(),
        "direct": "",
    }
    raw = source.get("SCRAPI_PROXY_PROFILES_JSON", "").strip()
    if not raw:
        return profiles

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProxyProfileError(f"SCRAPI_PROXY_PROFILES_JSON is invalid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ProxyProfileError("SCRAPI_PROXY_PROFILES_JSON must be a JSON object")

    for name, proxy_url in parsed.items():
        if not isinstance(name, str) or not PROFILE_NAME_RE.fullmatch(name):
            raise ProxyProfileError(f"Invalid proxy profile name: {name!r}")
        if name in {"current", "direct"}:
            raise ProxyProfileError(f"Proxy profile name is reserved: {name}")
        if not isinstance(proxy_url, str):
            raise ProxyProfileError(f"Proxy profile {name!r} must be a string URL")
        profiles[name] = proxy_url.strip()

    return profiles
