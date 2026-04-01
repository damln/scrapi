import logging
import re
from html import escape as html_escape
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

TWITTER_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
MAX_TITLE_LENGTH = 200
TCO_TIMEOUT = 5.0
FETCH_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    _client = httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=False)


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("twitter_fetcher client not initialized")
    return _client


def is_twitter_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in TWITTER_HOSTS


def _extract_status_path(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path or ""
    if re.match(r"^/[^/]+/status/\d+", path):
        return path
    return None


async def fetch_twitter(url: str) -> dict | None:
    """Fetch a Twitter/X URL. Returns a result dict or None on failure.

    Strategy: fxtwitter API → oEmbed fallback.
    Returns {"not_found": True, "http_status": 404} when the page is confirmed gone.
    """
    result = await _fetch_fxtwitter(url)
    if result:
        return result

    logger.info("fxtwitter failed for %s, falling back to oEmbed", url)
    return await _fetch_oembed(url)


async def _fetch_fxtwitter(url: str) -> dict | None:
    path = _extract_status_path(url)
    if not path:
        return None

    client = _get_client()
    try:
        resp = await client.get(f"https://api.fxtwitter.com{path}")
        if resp.status_code == 404:
            logger.warning("fxtwitter returned 404 for %s (tweet not found)", url)
            return {"not_found": True, "http_status": 404}

        if resp.status_code != 200:
            logger.warning("fxtwitter returned %d for %s", resp.status_code, url)
            return None

        data = resp.json()
        tweet = data.get("tweet")
        if not isinstance(tweet, dict):
            return None

        return _build_fxtwitter_result(url, tweet)
    except Exception as e:
        logger.warning("fxtwitter error for %s: %s", url, e)
        return None


def _build_fxtwitter_result(url: str, tweet: dict) -> dict:
    author = _deep_get(tweet, "author", "name") or ""
    screen_name = _deep_get(tweet, "author", "screen_name") or ""
    avatar_url = _deep_get(tweet, "author", "avatar_url") or ""
    tweet_text = tweet.get("text") or _deep_get(tweet, "raw_text", "text") or ""
    created_at = tweet.get("created_at") or ""
    views = tweet.get("views")
    likes = tweet.get("likes")
    retweets = tweet.get("retweets")

    article_title = _deep_get(tweet, "article", "title") or ""
    article_text = _extract_article_text(tweet)
    cover_image = _deep_get(tweet, "article", "cover_media", "media_info", "original_img_url") or ""

    media_images = _extract_media(tweet)
    og_image = cover_image or (media_images[0] if media_images else "") or avatar_url

    if article_title:
        title = _build_title(author, article_title)
    elif tweet_text and not _just_tco_link(tweet_text):
        title = _build_title(author, tweet_text)
    elif author:
        title = f"{author} on X"
    else:
        title = "Post on X"

    body_parts = []

    if tweet_text and not _just_tco_link(tweet_text):
        body_parts.append(f'<div class="tweet-text"><p>{html_escape(tweet_text)}</p></div>')

    if article_text:
        body_parts.append(f"<article>{article_text}</article>")

    for img in media_images:
        body_parts.append(f'<img src="{html_escape(img)}" />')

    stats_parts = []
    if views is not None:
        stats_parts.append(f"{views} views")
    if likes is not None:
        stats_parts.append(f"{likes} likes")
    if retweets is not None:
        stats_parts.append(f"{retweets} retweets")

    if stats_parts:
        body_parts.append(f'<p class="tweet-stats">{" · ".join(stats_parts)}</p>')

    description = tweet_text if tweet_text and not _just_tco_link(tweet_text) else ""

    html = f"""<html>
<head>
<meta property="og:site_name" content="X (formerly Twitter)">
<meta property="og:type" content="article">
<meta property="og:url" content="{html_escape(url)}">
<meta property="og:title" content="{html_escape(title)}">
<meta property="og:description" content="{html_escape(description)}">
<meta property="og:image" content="{html_escape(og_image)}">
<meta name="description" content="{html_escape(description)}">
<meta name="author" content="{html_escape(author)}">
<meta name="twitter:creator" content="@{html_escape(screen_name)}">
<title>{html_escape(title)}</title>
</head>
<body>
<header>
<strong>{html_escape(author)}</strong> <span>@{html_escape(screen_name)}</span>
<time>{html_escape(created_at)}</time>
</header>
{chr(10).join(body_parts)}
</body>
</html>"""

    return {"html": html.strip(), "title": title, "provider": "twitter"}


async def _fetch_oembed(url: str) -> dict | None:
    client = _get_client()
    try:
        resp = await client.get(
            "https://publish.twitter.com/oembed",
            params={"url": url},
        )
        if resp.status_code == 404:
            logger.warning("twitter oEmbed returned 404 for %s (page not found)", url)
            return {"not_found": True, "http_status": 404}

        if resp.status_code != 200:
            logger.warning("twitter oEmbed returned %d for %s", resp.status_code, url)
            return None

        body = resp.json()
        embed_html = body.get("html", "")
        if not embed_html:
            return None

        author = body.get("author_name", "")
        tweet_text = _extract_oembed_text(embed_html)
        title = _build_title(author, tweet_text)

        html = f"""<html>
<head>
<meta property="og:site_name" content="X (formerly Twitter)">
<meta property="og:type" content="article">
<meta property="og:url" content="{html_escape(url)}">
<meta property="og:title" content="{html_escape(title)}">
<meta property="og:description" content="{html_escape(tweet_text)}">
<meta name="description" content="{html_escape(tweet_text)}">
<meta name="author" content="{html_escape(author)}">
<title>{html_escape(title)}</title>
</head>
<body>{embed_html}</body>
</html>"""

        return {"html": html.strip(), "title": title, "provider": "twitter"}
    except Exception as e:
        logger.warning("twitter oEmbed error for %s: %s", url, e)
        return None


def _extract_oembed_text(embed_html: str) -> str:
    """Extract tweet text from oEmbed HTML blockquote."""
    matches = re.findall(r"<p[^>]*>(.*?)</p>", embed_html, re.DOTALL)
    if not matches:
        return ""
    text = " ".join(re.sub(r"<[^>]+>", "", m).strip() for m in matches)
    return text.strip()


def _extract_article_text(tweet: dict) -> str:
    blocks = _deep_get(tweet, "article", "content", "blocks")
    if not isinstance(blocks, list) or not blocks:
        return ""

    parts = []
    for block in blocks:
        text = block.get("text", "")
        block_type = block.get("type", "unstyled")

        tag_map = {
            "header-one": "h1",
            "header-two": "h2",
            "header-three": "h3",
            "unordered-list-item": "li",
            "ordered-list-item": "li",
        }

        if block_type == "atomic":
            continue
        tag = tag_map.get(block_type, "p")
        parts.append(f"<{tag}>{html_escape(text)}</{tag}>")

    return "\n".join(parts)


def _extract_media(tweet: dict) -> list[str]:
    photos = _deep_get(tweet, "media", "photos")
    if not isinstance(photos, list):
        return []
    return [p["url"] for p in photos if isinstance(p, dict) and p.get("url")]


def _just_tco_link(text: str) -> bool:
    return bool(re.match(r"^https?://t\.co/\S+$", text.strip()))


def _build_title(author: str, text: str) -> str:
    if text and author:
        return _truncate(f"{author}: {text}", MAX_TITLE_LENGTH)
    if text:
        return _truncate(text, MAX_TITLE_LENGTH)
    if author:
        return f"{author} on X"
    return "Post on X"


def _truncate(text: str, max_length: int) -> str:
    if len(text) > max_length:
        return text[: max_length - 1] + "…"
    return text


def _deep_get(d: dict, *keys):
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d
