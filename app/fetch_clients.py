from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app import asset_fetcher, cloak_fetcher, firecrawl_fetcher, twitter_fetcher, youtube_fetcher


@asynccontextmanager
async def fetch_clients() -> AsyncIterator[None]:
    """Open the shared httpx clients and browser pool used by the fetchers."""
    asset_fetcher.init_client()
    firecrawl_fetcher.init_client()
    twitter_fetcher.init_client()
    youtube_fetcher.init_client()
    cloak_fetcher.init_browser_pool()
    try:
        yield
    finally:
        await cloak_fetcher.close_browser_pool()
        await asset_fetcher.close_client()
        await firecrawl_fetcher.close_client()
        await twitter_fetcher.close_client()
        await youtube_fetcher.close_client()
