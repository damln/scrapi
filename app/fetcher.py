import asyncio

from scrapling.fetchers import StealthyFetcher

from app.config import FETCH_TIMEOUT_MS
from app.cookie_dismiss import dismiss_cookies
from app.html_rewriter import make_links_absolute, strip_inline_scripts, strip_large_styles


def fetch_single_url(url: str) -> dict:
    """Fetch a single URL using StealthyFetcher and return full HTML with absolute links."""
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=FETCH_TIMEOUT_MS,
            page_action=dismiss_cookies,
        )

        html = page.body if isinstance(page.body, str) else page.body.decode("utf-8", errors="replace")
        html = strip_inline_scripts(html)
        html = strip_large_styles(html)
        html = make_links_absolute(html, url)

        return {
            "url": url,
            "status": "success",
            "html": html,
        }
    except Exception as error:
        return {
            "url": url,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "html": None,
        }


async def fetch_urls(urls: list[str]) -> list[dict]:
    """Fetch multiple URLs concurrently using a thread pool."""
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, fetch_single_url, url) for url in urls]
    return await asyncio.gather(*tasks)
