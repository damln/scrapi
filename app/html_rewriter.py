import re
from urllib.parse import urljoin


def make_links_absolute(html: str, base_url: str) -> str:
    """Convert all relative URLs in HTML to absolute URLs."""
    LINK_ATTRIBUTES = [
        "href",
        "src",
        "action",
        "poster",
        "data-src",
        "data-href",
        "srcset",
    ]

    for attr in LINK_ATTRIBUTES:
        if attr == "srcset":
            html = _rewrite_srcset(html, attr, base_url)
        else:
            html = _rewrite_attribute(html, attr, base_url)

    return html


def _rewrite_attribute(html: str, attr: str, base_url: str) -> str:
    pattern = re.compile(
        rf'({attr}\s*=\s*["\'])([^"\']+)(["\'])',
        re.IGNORECASE,
    )

    def replacer(match: re.Match) -> str:
        prefix = match.group(1)
        value = match.group(2).strip()
        suffix = match.group(3)

        if _is_relative(value):
            value = urljoin(base_url, value)

        return f"{prefix}{value}{suffix}"

    return pattern.sub(replacer, html)


def _rewrite_srcset(html: str, attr: str, base_url: str) -> str:
    pattern = re.compile(
        rf'({attr}\s*=\s*["\'])([^"\']+)(["\'])',
        re.IGNORECASE,
    )

    def replacer(match: re.Match) -> str:
        prefix = match.group(1)
        raw = match.group(2)
        suffix = match.group(3)

        parts = []
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split()
            url = tokens[0]
            descriptor = " ".join(tokens[1:])
            if _is_relative(url):
                url = urljoin(base_url, url)
            parts.append(f"{url} {descriptor}".strip())

        return f"{prefix}{', '.join(parts)}{suffix}"

    return pattern.sub(replacer, html)


def strip_inline_scripts(html: str) -> str:
    """Remove <script> tags that have no src attribute (inline scripts)."""
    return re.sub(
        r"<script(?![^>]*\bsrc\s*=)[^>]*>[\s\S]*?</script>",
        "",
        html,
        flags=re.IGNORECASE,
    )


LARGE_STYLE_THRESHOLD_BYTES = 2048


def strip_large_styles(html: str) -> str:
    """Remove <style> tags whose content exceeds LARGE_STYLE_THRESHOLD_BYTES."""
    def replacer(match: re.Match) -> str:
        content = match.group(1)
        if len(content.encode("utf-8")) > LARGE_STYLE_THRESHOLD_BYTES:
            return ""
        return match.group(0)

    return re.sub(
        r"<style[^>]*>([\s\S]*?)</style>",
        replacer,
        html,
        flags=re.IGNORECASE,
    )


def strip_inline_styles(html: str) -> str:
    """Remove all inline style="..." attributes from HTML tags."""
    return re.sub(r'\s+style\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)


def _is_relative(url: str) -> bool:
    if not url:
        return False
    if url.startswith(("http://", "https://", "//", "data:", "mailto:", "tel:", "javascript:", "#")):
        return False
    return True
