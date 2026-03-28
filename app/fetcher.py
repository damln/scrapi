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


async def fetch_single_url(raw_url: str, no_style: bool = False) -> dict:
    """Fetch a URL with fallback chain: scrapling -> cloudflare -> firecrawl."""
    url = clean_url(raw_url)
    loop = asyncio.get_event_loop()

    # Step 1: Try scrapling
    try:
        logger.info("[scrapling] fetching %s", url)
        html = await loop.run_in_executor(None, _fetch_with_scrapling, url)
        html = _post_process(html, url, no_style)
        validation = validate_content(html)

        if validation["valid"]:
            logger.info("[scrapling] valid content for %s", url)
            return _success(url, raw_url, html, "scrapling", validation["scores"])

        logger.warning("[scrapling] content rejected for %s: %s", url, validation["reason"])
    except Exception as error:
        logger.warning("[scrapling] failed for %s: %s", url, error)

    # Step 2: Try Cloudflare
    if CLOUDFLARE_API_KEY:
        try:
            logger.info("[cloudflare] fetching %s", url)
            html = await fetch_with_cloudflare(url)
            html = _post_process(html, url, no_style)
            validation = validate_content(html)

            if validation["valid"]:
                logger.info("[cloudflare] valid content for %s", url)
                return _success(url, raw_url, html, "cloudflare", validation["scores"])

            logger.warning("[cloudflare] content rejected for %s: %s", url, validation["reason"])
        except Exception as error:
            logger.warning("[cloudflare] failed for %s: %s", url, error)
    else:
        logger.info("[cloudflare] skipped (no API key configured)")

    # Step 3: Try Firecrawl
    if FIRECRAWL_API_KEY:
        try:
            logger.info("[firecrawl] fetching %s", url)
            html = await fetch_with_firecrawl(url)
            html = _post_process(html, url, no_style)
            logger.info("[firecrawl] returning content for %s (last resort)", url)
            return _success(url, raw_url, html, "firecrawl")
        except Exception as error:
            logger.warning("[firecrawl] failed for %s: %s", url, error)
    else:
        logger.info("[firecrawl] skipped (no API key configured)")

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


async def fetch_urls(urls: list[str], no_style: bool = False) -> list[dict]:
    """Fetch multiple URLs concurrently with fallback chain."""
    tasks = [fetch_single_url(url, no_style) for url in urls]
    return await asyncio.gather(*tasks)
