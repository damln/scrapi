import logging
from html import escape as html_escape
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
FETCH_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    _client = httpx.AsyncClient(timeout=FETCH_TIMEOUT)


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("youtube_fetcher client not initialized")
    return _client


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in YOUTUBE_HOSTS


async def fetch_youtube(url: str) -> dict | None:
    """Fetch YouTube metadata via oEmbed API. Returns a result dict or None on failure."""
    client = _get_client()
    try:
        resp = await client.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
        )
        if resp.status_code != 200:
            logger.warning("youtube oEmbed returned %d for %s", resp.status_code, url)
            return None

        body = resp.json()
        title = body.get("title", "")
        author = body.get("author_name", "")
        thumbnail = body.get("thumbnail_url", "")
        embed_html = body.get("html", "")

        full_title = f"{title} — {author}" if author and title else title

        html = f"""<html>
<head>
<meta property="og:site_name" content="YouTube">
<meta property="og:type" content="video">
<meta property="og:url" content="{html_escape(url)}">
<meta property="og:title" content="{html_escape(title)}">
<meta property="og:image" content="{html_escape(thumbnail)}">
<meta name="author" content="{html_escape(author)}">
<title>{html_escape(full_title)}</title>
</head>
<body>{embed_html}</body>
</html>"""

        return {"html": html.strip(), "title": full_title, "provider": "youtube"}
    except Exception as e:
        logger.warning("youtube oEmbed error for %s: %s", url, e)
        return None
