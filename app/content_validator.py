import re

MIN_HTML_LENGTH = 256

BLOCKED_INDICATORS = [
    "access denied",
    "403 forbidden",
    "please enable javascript",
    "checking your browser",
    "just a moment",
    "attention required",
    "cloudflare ray id",
    "captcha",
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
    """Check whether HTML content looks like a real page vs a block/captcha page.

    Only rejects pages that are clearly blocked or empty.
    """
    scores = {}

    scores["html_length"] = len(html)
    if scores["html_length"] < MIN_HTML_LENGTH:
        return _fail("html_too_short", scores)

    has_body = bool(re.search(r"<body[\s>]", html, re.IGNORECASE))
    scores["has_body"] = has_body
    if not has_body:
        return _fail("no_body_tag", scores)

    html_lower = html.lower()
    blocked_matches = [kw for kw in BLOCKED_INDICATORS if kw in html_lower]
    scores["blocked_matches"] = blocked_matches
    if len(blocked_matches) >= 2:
        return _fail("blocked_page", scores)

    return {"valid": True, "reason": None, "scores": scores}


def _fail(reason: str, scores: dict) -> dict:
    return {"valid": False, "reason": reason, "scores": scores}
