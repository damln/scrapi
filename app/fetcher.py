import asyncio
import concurrent.futures
import functools
import logging

from scrapling.fetchers import StealthyFetcher

from app.cloudflare_fetcher import fetch_with_cloudflare
from app.config import CLOUDFLARE_API_KEY, FIRECRAWL_API_KEY, SCRAPLING_MAX_CONCURRENT, SCRAPLING_TIMEOUT_MS
from app.content_validator import validate_content
from app.cookie_dismiss import dismiss_cookies
from app.firecrawl_fetcher import fetch_with_firecrawl
from app.html_rewriter import extract_head_meta, html_to_markdown, make_links_absolute, strip_inline_scripts, strip_inline_styles, strip_large_styles
from app.twitter_fetcher import fetch_twitter, is_twitter_url
from app.url_cleaner import clean_url
from app.youtube_fetcher import fetch_youtube, is_youtube_url

logger = logging.getLogger(__name__)

_thread_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=SCRAPLING_MAX_CONCURRENT, thread_name_prefix="scrapling"
)

_scrapling_semaphore: asyncio.Semaphore | None = None

SCRAPLING_RETRY_ATTEMPTS = 2
SCRAPLING_RETRY_DELAY_S = 1.0

SCROLL_STEP_PX = 800
SCROLL_DELAY_MS = 400
SCROLL_MAX_ITERATIONS = 40
SCROLL_SETTLE_MS = 1500


def _get_scrapling_semaphore() -> asyncio.Semaphore:
    global _scrapling_semaphore
    if _scrapling_semaphore is None:
        _scrapling_semaphore = asyncio.Semaphore(SCRAPLING_MAX_CONCURRENT)
    return _scrapling_semaphore


def _sanitize_utf8(html: str) -> str:
    """Re-encode to UTF-8, replacing any surrogate or invalid byte sequences."""
    return html.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _post_process(html: str, url: str, no_style: bool, no_script: bool) -> tuple[str, dict, str | None]:
    html = _sanitize_utf8(html)
    head_meta = extract_head_meta(html)
    if no_script:
        html = strip_inline_scripts(html)
    html = strip_large_styles(html)
    if no_style:
        html = strip_inline_styles(html)
    html = make_links_absolute(html, url)
    markdown = html_to_markdown(html)
    return html, head_meta, markdown


def scroll_full_page(page):
    """Scroll the full page incrementally to trigger lazy-loaded content."""
    prev_height = page.evaluate("document.body.scrollHeight")

    for _ in range(SCROLL_MAX_ITERATIONS):
        current_pos = page.evaluate("window.pageYOffset")
        page.evaluate(f"window.scrollTo(0, {current_pos + SCROLL_STEP_PX})")
        page.wait_for_timeout(SCROLL_DELAY_MS)

        new_height = page.evaluate("document.body.scrollHeight")
        reached_bottom = page.evaluate(
            "window.pageYOffset + window.innerHeight >= document.body.scrollHeight - 50"
        )
        if reached_bottom and new_height == prev_height:
            break
        prev_height = new_height

    page.wait_for_timeout(SCROLL_SETTLE_MS)
    page.evaluate("window.scrollTo(0, 0)")
    return page


def dismiss_cookies_and_scroll(page):
    """Cookie dismissal followed by full-page scroll for lazy-load triggering."""
    page = dismiss_cookies(page)
    page = scroll_full_page(page)
    return page


def _fetch_with_scrapling(url: str, scroll_full: bool = False) -> str:
    """Fetch using StealthyFetcher. Raises on failure."""
    action = dismiss_cookies_and_scroll if scroll_full else dismiss_cookies
    page = StealthyFetcher.fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=SCRAPLING_TIMEOUT_MS,
        page_action=action,
        disable_ads=True,
    )
    html = page.body if isinstance(page.body, str) else page.body.decode("utf-8", errors="replace")
    return html


DEFAULT_PROVIDER_ORDER = ["raw", "cloudflare", "firecrawl"]

PROVIDER_API_KEYS = {
    "cloudflare": CLOUDFLARE_API_KEY,
    "firecrawl": FIRECRAWL_API_KEY,
}


async def _try_provider(
    provider: str, url: str, no_style: bool, no_script: bool, loop, is_last: bool = False, scroll_full: bool = False,
) -> tuple[str | None, dict | None, dict | None, str | None]:
    """Try a single provider. Returns (html, scores, head_meta, markdown) on success, (None, None, None, None) on failure.

    When is_last=True, skip content validation and return whatever HTML was fetched.
    The raw provider gets one retry on exception (transient browser failures).
    """
    if provider != "raw" and not PROVIDER_API_KEYS.get(provider):
        logger.info("[%s] skipped (no API key configured)", provider)
        return None, None, None, None

    attempts = SCRAPLING_RETRY_ATTEMPTS if provider == "raw" else 1

    for attempt in range(attempts):
        try:
            logger.info("[%s] fetching %s", provider, url)

            if provider == "raw":
                sem = _get_scrapling_semaphore()
                fn = functools.partial(_fetch_with_scrapling, url, scroll_full=scroll_full)
                async with sem:
                    html = await loop.run_in_executor(_thread_pool, fn)
            elif provider == "cloudflare":
                html = await fetch_with_cloudflare(url, scroll_full=scroll_full)
            elif provider == "firecrawl":
                html = await fetch_with_firecrawl(url)
            else:
                logger.warning("[%s] unknown provider", provider)
                return None, None, None, None

            html, head_meta, markdown = _post_process(html, url, no_style, no_script)
            validation = validate_content(html)

            if validation["valid"]:
                logger.info("[%s] valid content for %s", provider, url)
                return html, validation["scores"], head_meta, markdown

            if is_last:
                logger.warning("[%s] content weak for %s: %s (last provider, returning anyway)", provider, url, validation["reason"])
                return html, validation["scores"], head_meta, markdown

            logger.warning("[%s] content rejected for %s: %s", provider, url, validation["reason"])
            return None, None, None, None
        except Exception as error:
            if attempt < attempts - 1:
                logger.warning("[%s] attempt %d failed for %s: %s — retrying", provider, attempt + 1, url, error)
                await asyncio.sleep(SCRAPLING_RETRY_DELAY_S)
                continue
            logger.warning("[%s] failed for %s: %s", provider, url, error)

    return None, None, None, None


async def fetch_single_url(raw_url: str, no_style: bool = False, no_script: bool = False, provider_order: list[str] | None = None, scroll_full: bool = False) -> dict:
    """Fetch a URL trying providers in the given order."""
    url = clean_url(raw_url)

    # Special-case Twitter and YouTube — use dedicated API fetchers
    special_result = await _try_special_fetcher(url, raw_url)
    if special_result is not None:
        return special_result

    providers = provider_order or DEFAULT_PROVIDER_ORDER
    loop = asyncio.get_event_loop()

    for i, provider in enumerate(providers):
        is_last = i == len(providers) - 1
        html, scores, head_meta, markdown = await _try_provider(provider, url, no_style, no_script, loop, is_last, scroll_full=scroll_full)
        if html is not None:
            return _success(url, raw_url, html, provider, scores, head_meta, markdown)

    return {
        "url": url,
        "raw_url": raw_url,
        "status": "error",
        "provider": None,
        "error": "All providers failed to fetch valid content",
        "html": None,
    }


async def _try_special_fetcher(url: str, raw_url: str) -> dict | None:
    """Try Twitter or YouTube fetchers for known URL patterns."""
    result = None
    if is_twitter_url(url):
        result = await fetch_twitter(url)
    elif is_youtube_url(url):
        result = await fetch_youtube(url)

    if result is None:
        return None

    html = result["html"]
    head_meta = extract_head_meta(html)
    markdown = html_to_markdown(html)
    return _success(url, raw_url, html, result["provider"], None, head_meta, markdown)


def _success(url: str, raw_url: str, html: str, provider: str, scores: dict | None = None, head_meta: dict | None = None, markdown: str | None = None) -> dict:
    result = {
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
    return result


async def fetch_urls(urls: list[str], no_style: bool = False, no_script: bool = False, provider_order: list[str] | None = None, scroll_full: bool = False) -> list[dict]:
    """Fetch multiple URLs concurrently with fallback chain."""
    tasks = [fetch_single_url(url, no_style, no_script, provider_order, scroll_full=scroll_full) for url in urls]
    return await asyncio.gather(*tasks)
