import asyncio
import logging

from scrapling.fetchers import StealthyFetcher

from app.cloudflare_fetcher import fetch_with_cloudflare
from app.config import CLOUDFLARE_API_KEY, FIRECRAWL_API_KEY, SCRAPLING_TIMEOUT_MS
from app.content_validator import validate_content
from app.cookie_dismiss import dismiss_cookies
from app.firecrawl_fetcher import fetch_with_firecrawl
from app.html_rewriter import make_links_absolute, strip_inline_scripts, strip_inline_styles, strip_large_styles
from app.url_cleaner import clean_url

logger = logging.getLogger(__name__)


def _post_process(html: str, url: str, no_style: bool) -> str:
    html = strip_inline_scripts(html)
    html = strip_large_styles(html)
    if no_style:
        html = strip_inline_styles(html)
    html = make_links_absolute(html, url)
    return html


def _fetch_with_scrapling(url: str) -> str:
    """Fetch using StealthyFetcher. Raises on failure."""
    page = StealthyFetcher.fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=SCRAPLING_TIMEOUT_MS,
        page_action=dismiss_cookies,
        disable_ads=True,
    )
    html = page.body if isinstance(page.body, str) else page.body.decode("utf-8", errors="replace")
    return html


DEFAULT_PROVIDER_ORDER = ["raw", "cloudflare", "firecrawl"]

PROVIDER_API_KEYS = {
    "cloudflare": CLOUDFLARE_API_KEY,
    "firecrawl": FIRECRAWL_API_KEY,
}


async def _try_provider(provider: str, url: str, no_style: bool, loop) -> tuple[str | None, dict | None]:
    """Try a single provider. Returns (html, scores) on success, (None, None) on failure."""
    if provider != "raw" and not PROVIDER_API_KEYS.get(provider):
        logger.info("[%s] skipped (no API key configured)", provider)
        return None, None

    try:
        logger.info("[%s] fetching %s", provider, url)

        if provider == "raw":
            html = await loop.run_in_executor(None, _fetch_with_scrapling, url)
        elif provider == "cloudflare":
            html = await fetch_with_cloudflare(url)
        elif provider == "firecrawl":
            html = await fetch_with_firecrawl(url)
        else:
            logger.warning("[%s] unknown provider", provider)
            return None, None

        html = _post_process(html, url, no_style)
        validation = validate_content(html)

        if validation["valid"]:
            logger.info("[%s] valid content for %s", provider, url)
            return html, validation["scores"]

        logger.warning("[%s] content rejected for %s: %s", provider, url, validation["reason"])
    except Exception as error:
        logger.warning("[%s] failed for %s: %s", provider, url, error)

    return None, None


async def fetch_single_url(raw_url: str, no_style: bool = False, provider_order: list[str] | None = None) -> dict:
    """Fetch a URL trying providers in the given order."""
    url = clean_url(raw_url)
    providers = provider_order or DEFAULT_PROVIDER_ORDER
    loop = asyncio.get_event_loop()

    for provider in providers:
        html, scores = await _try_provider(provider, url, no_style, loop)
        if html is not None:
            return _success(url, raw_url, html, provider, scores)

    return {
        "url": url,
        "raw_url": raw_url,
        "status": "error",
        "provider": None,
        "error": "All providers failed to fetch valid content",
        "html": None,
    }


def _success(url: str, raw_url: str, html: str, provider: str, scores: dict | None = None) -> dict:
    result = {
        "url": url,
        "raw_url": raw_url,
        "status": "success",
        "provider": provider,
        "html": html,
    }
    if scores:
        result["scores"] = scores
    return result


async def fetch_urls(urls: list[str], no_style: bool = False, provider_order: list[str] | None = None) -> list[dict]:
    """Fetch multiple URLs concurrently with fallback chain."""
    tasks = [fetch_single_url(url, no_style, provider_order) for url in urls]
    return await asyncio.gather(*tasks)
