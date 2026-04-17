import os

API_TOKEN = os.environ["SCRAPI_API_TOKEN"]
FETCH_TIMEOUT_MS = int(os.environ.get("SCRAPI_FETCH_TIMEOUT_MS", "30000"))

SCRAPLING_TIMEOUT_MS = FETCH_TIMEOUT_MS
SCRAPLING_MAX_CONCURRENT = int(os.environ.get("SCRAPLING_MAX_CONCURRENT", "2"))

# Hard asyncio timeout per provider call (seconds). This is the safety net that
# kills a provider attempt if Scrapling's browser or an HTTP call hangs past its
# own internal timeout. Must be greater than the provider's own timeout.
PROVIDER_HARD_TIMEOUT_S = int(os.environ.get("PROVIDER_HARD_TIMEOUT_S", "45"))

# Hard asyncio timeout for the entire fetch_single_url call (all providers
# combined, including retries). Prevents a single URL from blocking forever.
FETCH_SINGLE_URL_TIMEOUT_S = int(os.environ.get("FETCH_SINGLE_URL_TIMEOUT_S", "120"))

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"
FIRECRAWL_TIMEOUT_SECONDS = int(os.environ.get("FIRECRAWL_TIMEOUT_SECONDS", "30"))

CLOUDFLARE_API_KEY = os.environ.get("CLOUDFLARE_API_KEY", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_TIMEOUT_SECONDS = int(os.environ.get("CLOUDFLARE_TIMEOUT_SECONDS", "30"))

PROXY_URL = os.environ.get("PROXY_URL", "")

# Cache configuration. Caching is opt-in per request via the `cache=<N>h`
# query parameter; there is no global TTL default.
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
CACHE_MAX_VERSIONS = int(os.environ.get("CACHE_MAX_VERSIONS", "5"))
CACHE_MAX_SIZE_BYTES = int(os.environ.get("CACHE_MAX_SIZE_GB", "20")) * 1024 * 1024 * 1024
