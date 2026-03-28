import re

MIN_HTML_LENGTH = 512
MIN_MEANINGFUL_TAGS = 5
MIN_TEXT_LENGTH = 200

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

MEANINGFUL_TAGS = re.compile(
    r"<(?:p|h[1-6]|li|td|th|article|section|main|figcaption|blockquote|dd|dt)[\s>]",
    re.IGNORECASE,
)

TAG_STRIPPER = re.compile(r"<[^>]+>")


def validate_content(html: str) -> dict:
    """Check whether HTML content is valid, non-blocked, and non-truncated.

    Returns a dict with:
      - valid (bool): whether the content passes all checks
      - reason (str | None): explanation if invalid
      - scores (dict): individual signal values for debugging
    """
    scores = {}

    scores["html_length"] = len(html)
    if scores["html_length"] < MIN_HTML_LENGTH:
        return _fail("html_too_short", scores)

    has_head = bool(re.search(r"<head[\s>]", html, re.IGNORECASE))
    has_body = bool(re.search(r"<body[\s>]", html, re.IGNORECASE))
    has_title = bool(re.search(r"<title[\s>][^<]*</title>", html, re.IGNORECASE))
    scores["has_head"] = has_head
    scores["has_body"] = has_body
    scores["has_title"] = has_title

    if not has_body:
        return _fail("no_body_tag", scores)

    html_lower = html.lower()
    blocked_matches = [kw for kw in BLOCKED_INDICATORS if kw in html_lower]
    scores["blocked_matches"] = blocked_matches
    if len(blocked_matches) >= 2:
        return _fail("blocked_page", scores)

    meaningful_count = len(MEANINGFUL_TAGS.findall(html))
    scores["meaningful_tags"] = meaningful_count
    if meaningful_count < MIN_MEANINGFUL_TAGS:
        return _fail("too_few_content_tags", scores)

    text = TAG_STRIPPER.sub("", html)
    text = re.sub(r"\s+", " ", text).strip()
    scores["text_length"] = len(text)
    if scores["text_length"] < MIN_TEXT_LENGTH:
        return _fail("text_too_short", scores)

    return {"valid": True, "reason": None, "scores": scores}


def _fail(reason: str, scores: dict) -> dict:
    return {"valid": False, "reason": reason, "scores": scores}
