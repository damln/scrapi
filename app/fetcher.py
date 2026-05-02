import asyncio
import json
import logging
import os
import signal
import sys

from app.cache import read_cache, write_cache
from app.cloudflare_fetcher import fetch_with_cloudflare
from app.config import CLOUDFLARE_API_KEY, FETCH_SINGLE_URL_TIMEOUT_S, FIRECRAWL_API_KEY, PROVIDER_HARD_TIMEOUT_S, SCRAPLING_MAX_CONCURRENT
from app.content_validator import validate_content
from app.firecrawl_fetcher import fetch_with_firecrawl
from app.html_rewriter import extract_head_meta, html_to_markdown, make_links_absolute, strip_inline_scripts, strip_inline_styles, strip_large_styles
from app.obscura_fetcher import fetch_with_obscura
from app.twitter_fetcher import fetch_twitter, is_twitter_url
from app.url_cleaner import clean_url
from app.youtube_fetcher import fetch_youtube, is_youtube_url

logger = logging.getLogger(__name__)

_scrapling_semaphore: asyncio.Semaphore | None = None

SCRAPLING_RETRY_ATTEMPTS = 2
SCRAPLING_RETRY_DELAY_S = 1.0


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


def _killpg(pid: int) -> None:
    """SIGKILL the process group for pid. Safe if the group is already gone."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning("killpg(%s) denied: %s", pgid, exc)


async def _fetch_with_scrapling(
    url: str,
    scroll_full: bool = False,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
) -> tuple[str, dict]:
    """Fetch using StealthyFetcher inside a killable subprocess.

    The fetch runs in `python -m app.fetcher_worker`. On cancellation or
    timeout the entire process group is SIGKILL'd so camoufox browsers
    can't linger — the old thread-pool approach leaked them because a
    thread stuck in C code ignores asyncio cancellation.
    """
    cmd = [sys.executable, "-m", "app.fetcher_worker", url]
    if scroll_full:
        cmd.append("--scroll-full")
    if wait_until:
        cmd.extend(["--wait-until", wait_until])
    if wait_for_selector:
        cmd.extend(["--wait-for-selector", wait_for_selector])

    # start_new_session=True puts the child in its own process group, so
    # one killpg call reaches camoufox and every helper it spawns.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        _killpg(proc.pid)
        # Reap so the OS doesn't hold a zombie.
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass
        raise

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"fetcher_worker exit {proc.returncode}: {err[:500]}")

    result = json.loads(stdout.decode("utf-8", errors="replace"))
    return result["html"], result.get("http_metadata") or {}


DEFAULT_PROVIDER_ORDER = ["obscura", "scrapling", "cloudflare", "firecrawl"]

# Providers that don't need an API key (they're local processes / binaries).
# Used by `_try_provider` to decide whether to skip a provider for missing
# credentials before spending time trying to invoke it.
KEYLESS_PROVIDERS = {"obscura", "scrapling"}

PROVIDER_API_KEYS = {
    "cloudflare": CLOUDFLARE_API_KEY,
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
) -> tuple[str | None, dict | None, dict | None, str | None, dict | None]:
    """Try a single provider. Returns (html, scores, head_meta, markdown, http_metadata) on success, (None, None, None, None, None) on failure.

    When is_last=True, skip content validation and return whatever HTML was fetched.
    The scrapling provider gets one retry on exception (transient browser failures).
    """
    if provider not in KEYLESS_PROVIDERS and not PROVIDER_API_KEYS.get(provider):
        logger.info("[%s] skipped (no API key configured)", provider)
        return None, None, None, None, None

    attempts = SCRAPLING_RETRY_ATTEMPTS if provider == "scrapling" else 1

    for attempt in range(attempts):
        try:
            logger.info("[%s] fetching %s (attempt %d/%d)", provider, url, attempt + 1, attempts)
            http_metadata = None

            if provider == "obscura":
                # No semaphore: obscura is ~30 MB/instance and starts instantly,
                # so it doesn't need the same concurrency throttle as Camoufox.
                # `scroll_full` is silently ignored — obscura's CLI has no
                # equivalent today; fall through to scrapling if scroll matters.
                html, http_metadata = await asyncio.wait_for(
                    fetch_with_obscura(
                        url,
                        wait_until=wait_until,
                        wait_for_selector=wait_for_selector,
                    ),
                    timeout=PROVIDER_HARD_TIMEOUT_S,
                )
            elif provider == "scrapling":
                sem = _get_scrapling_semaphore()
                async with sem:
                    html, http_metadata = await asyncio.wait_for(
                        _fetch_with_scrapling(
                            url,
                            scroll_full=scroll_full,
                            wait_until=wait_until,
                            wait_for_selector=wait_for_selector,
                        ),
                        timeout=PROVIDER_HARD_TIMEOUT_S,
                    )
            elif provider == "cloudflare":
                html = await asyncio.wait_for(
                    fetch_with_cloudflare(url, scroll_full=scroll_full),
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

            if is_last:
                logger.warning("[%s] content weak for %s: %s (last provider, returning anyway)", provider, url, validation["reason"])
                return html, validation["scores"], head_meta, markdown, http_metadata

            logger.warning("[%s] content rejected for %s: %s", provider, url, validation["reason"])
            return None, None, None, None, None
        except asyncio.TimeoutError:
            logger.error("[%s] hard timeout (%ds) for %s on attempt %d", provider, PROVIDER_HARD_TIMEOUT_S, url, attempt + 1)
            if attempt < attempts - 1:
                await asyncio.sleep(SCRAPLING_RETRY_DELAY_S)
                continue
        except Exception as error:
            if attempt < attempts - 1:
                logger.warning("[%s] attempt %d failed for %s: %s — retrying", provider, attempt + 1, url, error)
                await asyncio.sleep(SCRAPLING_RETRY_DELAY_S)
                continue
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
    cache_ttl_hours: float | None = None,
) -> dict:
    """Fetch a URL trying providers in the given order.

    When `cache_ttl_hours` is set, a cached result is served if within that TTL,
    and a successful fresh fetch is written to cache. When None, cache is not
    consulted and nothing is written.
    """
    url = clean_url(raw_url)

    if cache_ttl_hours is not None:
        cached = await asyncio.to_thread(read_cache, url, cache_ttl_hours)
        if cached is not None:
            cached["raw_url"] = raw_url
            return cached

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
            ),
            timeout=FETCH_SINGLE_URL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.error("Overall timeout (%ds) for %s — all providers exhausted or hung", FETCH_SINGLE_URL_TIMEOUT_S, url)
        return {
            "url": url,
            "raw_url": raw_url,
            "status": "error",
            "provider": None,
            "error": f"Overall fetch timeout ({FETCH_SINGLE_URL_TIMEOUT_S}s) — request took too long",
            "html": None,
        }

    if cache_ttl_hours is not None and result.get("status") == "success":
        await asyncio.to_thread(write_cache, url, result)

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
    cache_ttl_hours: float | None = None,
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
            cache_ttl_hours=cache_ttl_hours,
        )
        for url in urls
    ]
    return await asyncio.gather(*tasks)
