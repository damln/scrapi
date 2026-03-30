import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from markdownify import markdownify


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


MAX_HEAD_VALUE_LENGTH = 400

ALLOWED_HEAD_KEYS = {
    "title",
    "description",
    "keywords",
    "author",
    "canonical",
    "robots",
    "generator",
    "theme-color",
    "application-name",
    "apple-itunes-app",
    "google-play-app",
    "og:title",
    "og:description",
    "og:image",
    "og:url",
    "og:site_name",
    "og:type",
    "og:image:width",
    "og:image:height",
    "og:image:alt",
    "og:locale",
    "twitter:card",
    "twitter:site",
    "twitter:creator",
    "article:published_time",
    "article:modified_time",
    "article:author",
    "article:section",
    "al:ios:url",
    "al:ios:app_name",
}


class _HeadMetaParser(HTMLParser):
    """Extract metadata from <head>: title, meta name/property, link canonical."""

    def __init__(self):
        super().__init__()
        self.result = {}
        self._in_head = False
        self._in_title = False
        self._title_parts = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "head":
            self._in_head = True
            return
        if not self._in_head:
            return

        if tag_lower == "title":
            self._in_title = True
            self._title_parts = []
            return

        attrs_dict = dict(attrs)

        if tag_lower == "meta":
            key = attrs_dict.get("name") or attrs_dict.get("property")
            content = attrs_dict.get("content")
            if key and content and key in ALLOWED_HEAD_KEYS and len(content) <= MAX_HEAD_VALUE_LENGTH:
                self.result[key] = content

        if tag_lower == "link" and attrs_dict.get("rel") == "canonical":
            href = attrs_dict.get("href", "").strip()
            if href and len(href) <= MAX_HEAD_VALUE_LENGTH:
                self.result["canonical"] = href

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "head":
            self._in_head = False
        if tag_lower == "title" and self._in_title:
            self._in_title = False
            title = "".join(self._title_parts).strip()
            if title and len(title) <= MAX_HEAD_VALUE_LENGTH:
                self.result["title"] = title

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)


def extract_head_meta(html: str) -> dict:
    """Extract key/value metadata from HTML <head>."""
    parser = _HeadMetaParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.result


MAX_HTML_SIZE_FOR_MARKDOWN = 5_000_000


def html_to_markdown(html: str) -> str | None:
    """Convert HTML to Markdown. Returns None if HTML is too large or conversion fails."""
    if len(html.encode("utf-8", errors="replace")) > MAX_HTML_SIZE_FOR_MARKDOWN:
        return None
    try:
        result = markdownify(html, heading_style="ATX", code_language="", strip=["script", "style", "svg"])
        return result.strip() if result else None
    except Exception:
        return None


def _is_relative(url: str) -> bool:
    if not url:
        return False
    if url.startswith(("http://", "https://", "//", "data:", "mailto:", "tel:", "javascript:", "#")):
        return False
    return True
