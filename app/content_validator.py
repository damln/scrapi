import re

MIN_HTML_LENGTH = 256

# High-confidence block markers — a SINGLE occurrence is enough to fail
# validation. These are vendor-specific challenge-page strings that don't
# legitimately appear in real article/listing content. Only add a marker
# here if a false positive is implausible (e.g. no real site embeds
# `geo.captcha-delivery.com` in its DOM unless DataDome served it).
HARD_BLOCK_MARKERS = [
    # DataDome challenge / captcha iframe.
    "geo.captcha-delivery.com",
    "datadome captcha",
    # Cloudflare bot management / managed challenge — these tokens appear
    # in CF's challenge interstitial, never in real content.
    "cf-mitigated",
    "cf-chl-bypass",
    "__cf_chl_jschl_tk__",
    "cf_chl_opt",
    # PerimeterX / HUMAN — challenge token in their interstitial.
    "px-captcha",
    "_px2",
    # coches.net / Adevinta interruption and hCaptcha shell markers.
    "js.hcaptcha.com/1/api.js",
    "ups! parece que algo no va bien",
    "interruption-message",
]

# Soft block indicators — phrases that could plausibly appear on real
# pages (a help article about CAPTCHAs, a blog post about Cloudflare,
# an error doc explaining 403s). We require >= 2 distinct matches before
# failing validation, on the theory that real pages won't trip multiple
# of these at once.
# Bare "captcha" is intentionally excluded: it is a substring of
# "recaptcha" / "hcaptcha", so pages with those widgets would count one
# signal twice. HARD_BLOCK_MARKERS already cover real challenge pages.
BLOCKED_INDICATORS = [
    "access denied",
    "403 forbidden",
    "please enable javascript",
    "checking your browser",
    "just a moment",
    "attention required",
    "cloudflare ray id",
    "recaptcha",
    "hcaptcha",
    "bot detection",
    "are you a robot",
    "please verify you are a human",
    "blocked your ip",
    "rate limit exceeded",
    "too many requests",
    "security check",
    "pardon our interruption",
    "why have i been blocked",
]


def validate_content(html: str) -> dict:
    """Check whether HTML content looks like a real page vs a block/captcha page."""
    scores: dict[str, object] = {}

    html_length = len(html)
    scores["html_length"] = html_length
    if html_length < MIN_HTML_LENGTH:
        return _fail("html_too_short", scores)

    has_body = bool(re.search(r"<body[\s>]", html, re.IGNORECASE))
    scores["has_body"] = has_body
    if not has_body:
        return _fail("no_body_tag", scores)

    html_lower = html.lower()

    hard_matches = [kw for kw in HARD_BLOCK_MARKERS if kw in html_lower]
    scores["hard_block_matches"] = hard_matches
    if hard_matches:
        return _fail(f"hard_block: {hard_matches[0]}", scores)

    blocked_matches = [kw for kw in BLOCKED_INDICATORS if kw in html_lower]
    scores["blocked_matches"] = blocked_matches
    if len(blocked_matches) >= 2:
        return _fail("blocked_page", scores)

    return {"valid": True, "reason": None, "scores": scores}


def _fail(reason: str, scores: dict) -> dict:
    return {"valid": False, "reason": reason, "scores": scores}
