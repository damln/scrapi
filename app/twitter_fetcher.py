import asyncio
import logging
import math
import re
from html import escape as html_escape
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import PROXY_URL

logger = logging.getLogger(__name__)

TWITTER_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
MAX_TITLE_LENGTH = 200
TCO_TIMEOUT = 5.0
FETCH_TIMEOUT = 30.0
RETRY_ATTEMPTS = 2
RETRY_DELAY_S = 2.0
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
# Cap thread walking so a runaway conversation (or a cycle in the data) can't
# fan out into an unbounded number of upstream fetches.
MAX_THREAD_HOPS = 5

# fxtwitter sits behind Cloudflare, which 403s httpx's default "python-httpx/*"
# User-Agent. A real desktop-browser UA avoids the challenge and mirrors what
# asset_fetcher already uses. The oEmbed endpoint is also happier with it.
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, */*;q=0.8",
}

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    kwargs: dict[str, Any] = {
        "timeout": FETCH_TIMEOUT,
        "follow_redirects": False,
        "headers": _DEFAULT_HEADERS,
    }
    if PROXY_URL:
        kwargs["proxy"] = PROXY_URL
    _client = httpx.AsyncClient(**kwargs)


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


def _extract_screen_name(url: str) -> str:
    """Extract the @username from a Twitter/X status URL path."""
    parsed = urlparse(url)
    match = re.match(r"^/([^/]+)/status/\d+", parsed.path or "")
    return match.group(1) if match else ""


async def fetch_twitter(url: str) -> dict | None:
    """Fetch a Twitter/X URL. Returns a result dict or None on failure.

    Strategy: fxtwitter API → oEmbed → syndication API.
    Returns {"not_found": True, "http_status": 404} when the page is confirmed gone.
    """
    result = await _fetch_fxtwitter(url)
    if result:
        return result

    logger.info("fxtwitter failed for %s, falling back to oEmbed", url)
    result = await _fetch_oembed(url)
    if result:
        return result

    logger.info("oEmbed failed for %s, falling back to syndication API", url)
    return await _fetch_syndication(url)


# Sentinel-style return from _fetch_tweet_by_path: either a tweet dict, a
# 404 marker, or None for transient failures. Keeping this in one place so
# both the leaf fetch and the thread walk share retry/error semantics.
_NOT_FOUND = object()


async def _fetch_tweet_by_path(path: str) -> dict | None | object:
    """Call api.fxtwitter.com<path> with retries. Returns the `tweet` dict,
    `_NOT_FOUND` on HTTP 404, or None on any other failure."""
    client = _get_client()

    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = await client.get(f"https://api.fxtwitter.com{path}")
            if resp.status_code == 404:
                return _NOT_FOUND

            if resp.status_code in RETRYABLE_STATUSES:
                logger.warning(
                    "fxtwitter returned %d for %s (attempt %d/%d)", resp.status_code, path, attempt + 1, RETRY_ATTEMPTS
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_DELAY_S)
                    continue
                return None

            if resp.status_code != 200:
                logger.warning("fxtwitter returned %d for %s", resp.status_code, path)
                return None

            data = resp.json()
            tweet = data.get("tweet")
            if not isinstance(tweet, dict):
                return None
            return tweet
        except Exception as e:
            logger.warning("fxtwitter error for %s: %s (attempt %d/%d)", path, e, attempt + 1, RETRY_ATTEMPTS)
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY_S)
                continue
            return None

    return None


async def _walk_thread(leaf: dict) -> list[dict]:
    """Walk upward from the leaf via replying_to_status. Returns parent tweets
    oldest-first (root → closest-to-leaf). Capped at MAX_THREAD_HOPS. A failed
    parent fetch aborts the walk — we return what we collected so far so the
    leaf can still render normally."""
    seen: set[str] = set()
    if leaf.get("id"):
        seen.add(str(leaf["id"]))

    parents: list[dict] = []
    cursor = leaf
    for _ in range(MAX_THREAD_HOPS):
        parent_id = cursor.get("replying_to_status")
        if not parent_id or str(parent_id) in seen:
            break
        seen.add(str(parent_id))

        # fxtwitter accepts `_` as a user placeholder — no need to resolve the
        # handle, which would require an extra lookup.
        parent = await _fetch_tweet_by_path(f"/_/status/{parent_id}")
        if not isinstance(parent, dict):
            break

        parents.append(parent)
        cursor = parent

    parents.reverse()
    return parents


async def _fetch_fxtwitter(url: str) -> dict | None:
    path = _extract_status_path(url)
    if not path:
        return None

    tweet = await _fetch_tweet_by_path(path)
    if tweet is _NOT_FOUND:
        logger.warning("fxtwitter returned 404 for %s (tweet not found)", url)
        return {"not_found": True, "http_status": 404}
    if not isinstance(tweet, dict):
        return None

    thread_parents = await _walk_thread(tweet) if tweet.get("replying_to_status") else []
    return _build_fxtwitter_result(url, tweet, thread_parents=thread_parents)


def _build_fxtwitter_result(url: str, tweet: dict, thread_parents: list[dict] | None = None) -> dict:
    thread_parents = thread_parents or []

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

    # Title precedence: leaf article title > leaf meaningful text > root parent's
    # article/text (useful when the leaf is a bare "thanks!" reply on a long thread)
    # > author fallback.
    if article_title:
        title = _build_title(author, screen_name, article_title)
    elif tweet_text and not _just_tco_link(tweet_text):
        title = _build_title(author, screen_name, tweet_text)
    else:
        root_title = _title_from_thread(thread_parents)
        title = root_title or _author_fallback_title(author, screen_name)

    body_parts: list[str] = []

    # Thread ancestors first (oldest → newest), so the reader sees the
    # conversation in chronological order leading into the leaf tweet.
    if thread_parents:
        ancestor_chunks = [_render_ancestor(p) for p in thread_parents]
        body_parts.append('<section class="thread-ancestors">\n' + "\n".join(ancestor_chunks) + "\n</section>")

    if tweet_text and not _just_tco_link(tweet_text):
        body_parts.append(f'<div class="tweet-text"><p>{html_escape(tweet_text)}</p></div>')

    if article_text:
        body_parts.append(f"<article>{article_text}</article>")

    for img in media_images:
        body_parts.append(f'<img src="{html_escape(img)}" />')

    quote = tweet.get("quote")
    if isinstance(quote, dict):
        body_parts.append(_render_quote(quote))

    stats_parts = []
    if views is not None:
        stats_parts.append(f"{views} views")
    if likes is not None:
        stats_parts.append(f"{likes} likes")
    if retweets is not None:
        stats_parts.append(f"{retweets} retweets")

    if stats_parts:
        body_parts.append(f'<p class="tweet-stats">{" · ".join(stats_parts)}</p>')

    description = _build_description(tweet_text, thread_parents, tweet)

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

    return {"html": html.strip(), "title": title, "provider": "twitter", "twitter_source": "fxtwitter"}


def _render_ancestor(parent: dict) -> str:
    """Render one thread ancestor as a self-contained <article>. Includes
    author, text, article content, and images — but not stats or QRT (we don't
    recurse into QRTs inside ancestors; too chatty, and fxtwitter only gives us
    the immediate parent chain)."""
    author = _deep_get(parent, "author", "name") or ""
    screen_name = _deep_get(parent, "author", "screen_name") or ""
    text = parent.get("text") or _deep_get(parent, "raw_text", "text") or ""
    article_title = _deep_get(parent, "article", "title") or ""
    article_text = _extract_article_text(parent)
    media = _extract_media(parent)

    parts = [
        '<article class="thread-ancestor">',
        f"<header><strong>{html_escape(author)}</strong> <span>@{html_escape(screen_name)}</span></header>",
    ]
    if text and not _just_tco_link(text):
        parts.append(f"<p>{html_escape(text)}</p>")
    if article_title:
        parts.append(f"<h2>{html_escape(article_title)}</h2>")
    if article_text:
        parts.append(f"<section>{article_text}</section>")
    for img in media:
        parts.append(f'<img src="{html_escape(img)}" />')
    parts.append("</article>")
    return "\n".join(parts)


def _render_quote(quote: dict) -> str:
    """Render a quoted tweet (QRT) as a blockquote nested under the leaf."""
    author = _deep_get(quote, "author", "name") or ""
    screen_name = _deep_get(quote, "author", "screen_name") or ""
    text = quote.get("text") or _deep_get(quote, "raw_text", "text") or ""
    article_title = _deep_get(quote, "article", "title") or ""
    article_text = _extract_article_text(quote)
    media = _extract_media(quote)

    parts = [
        '<blockquote class="quoted-tweet">',
        f"<strong>{html_escape(author)}</strong> <span>@{html_escape(screen_name)}</span>",
    ]
    if text and not _just_tco_link(text):
        parts.append(f"<p>{html_escape(text)}</p>")
    if article_title:
        parts.append(f"<p><em>{html_escape(article_title)}</em></p>")
    if article_text:
        parts.append(f"<section>{article_text}</section>")
    for img in media:
        parts.append(f'<img src="{html_escape(img)}" />')
    parts.append("</blockquote>")
    return "\n".join(parts)


def _title_from_thread(parents: list[dict]) -> str:
    """If the leaf has no meaningful content, borrow a title from the root of
    the thread — typically the OP of a conversation."""
    if not parents:
        return ""
    root = parents[0]
    author = _deep_get(root, "author", "name") or ""
    screen_name = _deep_get(root, "author", "screen_name") or ""
    article_title = _deep_get(root, "article", "title") or ""
    if article_title:
        return _build_title(author, screen_name, article_title)
    text = root.get("text") or _deep_get(root, "raw_text", "text") or ""
    if text and not _just_tco_link(text):
        return _build_title(author, screen_name, text)
    return ""


def _build_description(leaf_text: str, parents: list[dict], leaf: dict) -> str:
    """og:description — prefer leaf text, else first meaningful parent text,
    else empty. Keeps social cards useful for thin leaf tweets."""
    if leaf_text and not _just_tco_link(leaf_text):
        return leaf_text
    article_preview = _deep_get(leaf, "article", "preview_text")
    if isinstance(article_preview, str) and article_preview:
        return article_preview
    for p in parents:
        t = p.get("text") or _deep_get(p, "raw_text", "text") or ""
        if t and not _just_tco_link(t):
            return t
    return ""


async def _fetch_oembed(url: str) -> dict | None:
    client = _get_client()

    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = await client.get(
                "https://publish.twitter.com/oembed",
                params={"url": url},
            )
            if resp.status_code == 404:
                logger.warning("twitter oEmbed returned 404 for %s (page not found)", url)
                return {"not_found": True, "http_status": 404}

            if resp.status_code in RETRYABLE_STATUSES:
                logger.warning(
                    "twitter oEmbed returned %d for %s (attempt %d/%d)",
                    resp.status_code,
                    url,
                    attempt + 1,
                    RETRY_ATTEMPTS,
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_DELAY_S)
                    continue
                return None

            if resp.status_code != 200:
                logger.warning("twitter oEmbed returned %d for %s", resp.status_code, url)
                return None

            body = resp.json()
            embed_html = body.get("html", "")
            if not embed_html:
                return None

            author = body.get("author_name", "")
            screen_name = _extract_screen_name(url)
            tweet_text = _extract_oembed_text(embed_html)
            title = _build_title(author, screen_name, tweet_text)

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

            return {"html": html.strip(), "title": title, "provider": "twitter", "twitter_source": "oembed"}
        except Exception as e:
            logger.warning("twitter oEmbed error for %s: %s (attempt %d/%d)", url, e, attempt + 1, RETRY_ATTEMPTS)
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY_S)
                continue
            return None

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


def _author_fallback_title(author: str, screen_name: str) -> str:
    """Fallback title when there is no meaningful tweet text or article."""
    if screen_name:
        return f"Post by @{screen_name}"
    if author:
        return f"Post by {author}"
    return "Post on X"


def _build_title(author: str, screen_name: str, text: str) -> str:
    if text and author:
        return _truncate(f"{author}: {text}", MAX_TITLE_LENGTH)
    if text:
        return _truncate(text, MAX_TITLE_LENGTH)
    return _author_fallback_title(author, screen_name)


def _truncate(text: str, max_length: int) -> str:
    if len(text) > max_length:
        return text[: max_length - 1] + "…"
    return text


def _deep_get(d: dict, *keys: str) -> Any:
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# Syndication API (tertiary fallback)
# cdn.syndication.twimg.com is the unofficial-but-long-lived endpoint that
# powers Twitter's embed widgets. It accepts any tweet ID with a derived
# token and returns text + author + (for articles) a short preview. That's
# weaker than fxtwitter for long-form articles (article body → preview_text
# only, ~2 paragraphs), but it's the best source when fxtwitter is down AND
# oEmbed is useless (it is useless for article-only tweets: just the t.co).

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _syndication_token(tweet_id: str) -> str:
    """Port of the JS snippet that cdn.syndication.twimg.com's embed widget
    uses to derive the `token` query param. Must match byte-for-byte or the
    endpoint returns a generic 403."""
    v = (int(tweet_id) / 1e15) * math.pi
    intp = int(v)
    frac = v - intp

    if intp == 0:
        int_s = "0"
    else:
        int_s = ""
        n = intp
        while n > 0:
            int_s = _BASE36[n % 36] + int_s
            n //= 36

    frac_s = ""
    for _ in range(12):
        frac *= 36
        d = int(frac)
        frac -= d
        frac_s += _BASE36[d]

    raw = int_s + "." + frac_s
    return re.sub(r"(0+|\.)", "", raw)


async def _fetch_syndication(url: str) -> dict | None:
    path = _extract_status_path(url)
    if not path:
        return None
    m = re.match(r"^/[^/]+/status/(\d+)", path)
    if not m:
        return None
    tweet_id = m.group(1)

    client = _get_client()
    token = _syndication_token(tweet_id)

    try:
        resp = await client.get(
            "https://cdn.syndication.twimg.com/tweet-result",
            params={"id": tweet_id, "token": token, "lang": "en"},
        )
    except Exception as e:
        logger.warning("syndication error for %s: %s", url, e)
        return None

    if resp.status_code == 404:
        logger.warning("syndication returned 404 for %s", url)
        return {"not_found": True, "http_status": 404}
    if resp.status_code != 200:
        logger.warning("syndication returned %d for %s", resp.status_code, url)
        return None

    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    author = _deep_get(data, "user", "name") or ""
    screen_name = _deep_get(data, "user", "screen_name") or _extract_screen_name(url)
    text = data.get("text") or ""
    created_at = data.get("created_at") or ""
    article_title = _deep_get(data, "article", "title") or ""
    article_preview = _deep_get(data, "article", "preview_text") or ""

    if article_title:
        title = _build_title(author, screen_name, article_title)
    elif text and not _just_tco_link(text):
        title = _build_title(author, screen_name, text)
    else:
        title = _author_fallback_title(author, screen_name)

    body_parts = []
    if text and not _just_tco_link(text):
        body_parts.append(f"<p>{html_escape(text)}</p>")
    if article_title:
        body_parts.append(f"<h1>{html_escape(article_title)}</h1>")
    if article_preview:
        body_parts.append(f"<p>{html_escape(article_preview)}</p>")

    description = text if (text and not _just_tco_link(text)) else article_preview

    html = f"""<html>
<head>
<meta property="og:site_name" content="X (formerly Twitter)">
<meta property="og:type" content="article">
<meta property="og:url" content="{html_escape(url)}">
<meta property="og:title" content="{html_escape(title)}">
<meta property="og:description" content="{html_escape(description)}">
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

    return {"html": html.strip(), "title": title, "provider": "twitter", "twitter_source": "syndication"}
