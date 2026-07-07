import asyncio
import logging
from typing import Any

from app.cloak_fetcher import fetch_with_cloak
from app.config import (
    BROWSER_MAX_CONCURRENT,
    FETCH_SINGLE_URL_TIMEOUT_S,
    FIRECRAWL_API_KEY,
    PROVIDER_HARD_TIMEOUT_S,
)
from app.content_validator import validate_content
from app.firecrawl_fetcher import fetch_with_firecrawl
from app.html_rewriter import (
    extract_head_meta,
    html_to_markdown,
    make_links_absolute,
    strip_data_url_images,
    strip_inline_scripts,
    strip_inline_styles,
    strip_large_styles,
)
from app.proxy_profiles import resolve_proxy_profile
from app.twitter_fetcher import fetch_twitter, is_twitter_url
from app.url_cleaner import clean_url
from app.youtube_fetcher import fetch_youtube, is_youtube_url

logger = logging.getLogger(__name__)

_browser_semaphore: asyncio.Semaphore | None = None


def _get_browser_semaphore() -> asyncio.Semaphore:
    """Cap on concurrent Chromium instances (cloak provider).

    Each instance is ~500 MB; running too many in parallel OOMs the host.
    """
    global _browser_semaphore
    if _browser_semaphore is None:
        _browser_semaphore = asyncio.Semaphore(BROWSER_MAX_CONCURRENT)
    return _browser_semaphore


def _sanitize_utf8(html: str) -> str:
    """Re-encode to UTF-8, replacing any surrogate or invalid byte sequences."""
    return html.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _post_process(html: str, url: str, no_style: bool, no_script: bool) -> tuple[str, dict, str | None]:
    html = _sanitize_utf8(html)
    head_meta = extract_head_meta(html)
    # Strip inline base64 image blobs early — must run BEFORE markdownify
    # so markdown bodies don't carry the bloat through. Always-on; the
    # regex is sub-ms on pages that don't contain any.
    html = strip_data_url_images(html)
    if no_script:
        html = strip_inline_scripts(html)
    html = strip_large_styles(html)
    if no_style:
        html = strip_inline_styles(html)
    html = make_links_absolute(html, url)
    markdown = html_to_markdown(html)
    return html, head_meta, markdown


DEFAULT_PROVIDER_ORDER = ["cloak", "firecrawl"]

# Providers that don't need an API key (they're local processes / binaries).
# Used by `_try_provider` to decide whether to skip a provider for missing
# credentials before spending time trying to invoke it.
KEYLESS_PROVIDERS = {"cloak"}

PROVIDER_API_KEYS = {
    "firecrawl": FIRECRAWL_API_KEY,
}


async def _try_provider(
    provider: str,
    url: str,
    no_style: bool,
    no_script: bool,
    is_last: bool = False,
    scroll_full: bool = False,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
    proxy_profile: str = "current",
) -> tuple[str | None, dict | None, dict | None, str | None, dict | None]:
    """Try a single provider. Returns (html, scores, head_meta, markdown, http_metadata) on success, (None, None, None, None, None) on failure."""
    if provider not in KEYLESS_PROVIDERS and not PROVIDER_API_KEYS.get(provider):
        logger.info("[%s] skipped (no API key configured)", provider)
        return None, None, None, None, None

    try:
        logger.info("[%s] fetching %s", provider, url)
        http_metadata = None

        if provider == "cloak":
            proxy_url = resolve_proxy_profile(proxy_profile)
            sem = _get_browser_semaphore()
            async with sem:
                html, http_metadata = await asyncio.wait_for(
                    fetch_with_cloak(
                        url,
                        scroll_full=scroll_full,
                        wait_until=wait_until,
                        wait_for_selector=wait_for_selector,
                        proxy_url=proxy_url,
                    ),
                    timeout=PROVIDER_HARD_TIMEOUT_S,
                )
        elif provider == "firecrawl":
            html = await asyncio.wait_for(
                fetch_with_firecrawl(url),
                timeout=PROVIDER_HARD_TIMEOUT_S,
            )
        else:
            logger.warning("[%s] unknown provider", provider)
            return None, None, None, None, None

        html, head_meta, markdown = _post_process(html, url, no_style, no_script)
        validation = validate_content(html)

        if validation["valid"]:
            logger.info("[%s] valid content for %s", provider, url)
            return html, validation["scores"], head_meta, markdown, http_metadata

        suffix = " (last provider)" if is_last else ""
        logger.warning("[%s] content rejected%s for %s: %s", provider, suffix, url, validation["reason"])
        return None, None, None, None, None
    except TimeoutError:
        logger.exception("[%s] hard timeout (%ds) for %s", provider, PROVIDER_HARD_TIMEOUT_S, url)
    except Exception as error:
        logger.warning("[%s] failed for %s: %s", provider, url, error)

    return None, None, None, None, None


async def fetch_single_url(
    raw_url: str,
    no_style: bool = False,
    no_script: bool = False,
    provider_order: list[str] | None = None,
    scroll_full: bool = False,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
    proxy_profile: str = "current",
) -> dict:
    """Fetch a URL trying providers in the given order."""
    url = clean_url(raw_url)

    try:
        result = await asyncio.wait_for(
            _fetch_single_url_inner(
                url,
                raw_url,
                no_style,
                no_script,
                provider_order,
                scroll_full,
                wait_until,
                wait_for_selector,
                proxy_profile,
            ),
            timeout=FETCH_SINGLE_URL_TIMEOUT_S,
        )
    except TimeoutError:
        logger.exception(
            "Overall timeout (%ds) for %s — all providers exhausted or hung", FETCH_SINGLE_URL_TIMEOUT_S, url
        )
        return {
            "url": url,
            "raw_url": raw_url,
            "status": "error",
            "provider": None,
            "error": f"Overall fetch timeout ({FETCH_SINGLE_URL_TIMEOUT_S}s) — request took too long",
            "html": None,
        }

    return result


async def _fetch_single_url_inner(
    url: str,
    raw_url: str,
    no_style: bool,
    no_script: bool,
    provider_order: list[str] | None,
    scroll_full: bool,
    wait_until: str | None,
    wait_for_selector: str | None,
    proxy_profile: str,
) -> dict:
    """Inner fetch logic, separated so fetch_single_url can wrap it with a hard timeout."""
    # Special-case Twitter and YouTube — use dedicated API fetchers
    special_result = await _try_special_fetcher(url, raw_url)
    if special_result is not None:
        return special_result

    providers = provider_order or DEFAULT_PROVIDER_ORDER

    for i, provider in enumerate(providers):
        is_last = i == len(providers) - 1
        html, scores, head_meta, markdown, http_metadata = await _try_provider(
            provider,
            url,
            no_style,
            no_script,
            is_last,
            scroll_full=scroll_full,
            wait_until=wait_until,
            wait_for_selector=wait_for_selector,
            proxy_profile=proxy_profile,
        )
        if html is not None:
            return _success(url, raw_url, html, provider, scores, head_meta, markdown, http_metadata)

    return {
        "url": url,
        "raw_url": raw_url,
        "status": "error",
        "provider": None,
        "error": "All providers failed to fetch valid content",
        "html": None,
    }


async def _try_special_fetcher(url: str, raw_url: str) -> dict | None:
    """Try Twitter or YouTube fetchers for known URL patterns.

    Returns a success dict, a not-found dict (with http.status=404), or None to fall through.
    """
    result = None
    if is_twitter_url(url):
        result = await fetch_twitter(url)
    elif is_youtube_url(url):
        result = await fetch_youtube(url)

    if result is None:
        return None

    if result.get("not_found"):
        http_status = result.get("http_status", 404)
        provider = "youtube" if is_youtube_url(url) else "twitter"
        logger.info("Special fetcher confirmed %d for %s — returning error", http_status, url)
        return {
            "url": url,
            "raw_url": raw_url,
            "status": "error",
            "provider": provider,
            "error": f"Not found ({http_status})",
            "html": None,
        }

    html = result["html"]
    head_meta = extract_head_meta(html)
    markdown = html_to_markdown(html)
    return _success(
        url,
        raw_url,
        html,
        result["provider"],
        None,
        head_meta,
        markdown,
        twitter_source=result.get("twitter_source"),
    )


def _success(
    url: str,
    raw_url: str,
    html: str,
    provider: str,
    scores: dict | None = None,
    head_meta: dict | None = None,
    markdown: str | None = None,
    http_metadata: dict | None = None,
    twitter_source: str | None = None,
) -> dict:
    result: dict[str, Any] = {
        "url": url,
        "raw_url": raw_url,
        "status": "success",
        "provider": provider,
        "html": html,
    }
    if scores:
        result["scores"] = scores
    if head_meta:
        result["head_meta"] = head_meta
    if markdown:
        result["markdown"] = markdown
    if http_metadata:
        result["http"] = http_metadata
    # Sub-provider identifier for Twitter — lets downstream consumers tell
    # fxtwitter (rich) from oembed (thin) from syndication (fallback) apart
    # without having to content-sniff the HTML.
    if twitter_source:
        result["twitter_source"] = twitter_source
    return result


async def fetch_urls(
    urls: list[str],
    no_style: bool = False,
    no_script: bool = False,
    provider_order: list[str] | None = None,
    scroll_full: bool = False,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
    proxy_profile: str = "current",
) -> list[dict]:
    """Fetch multiple URLs concurrently with fallback chain."""
    tasks = [
        fetch_single_url(
            url,
            no_style,
            no_script,
            provider_order,
            scroll_full=scroll_full,
            wait_until=wait_until,
            wait_for_selector=wait_for_selector,
            proxy_profile=proxy_profile,
        )
        for url in urls
    ]
    return await asyncio.gather(*tasks)
