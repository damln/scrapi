import os

# Required to serve the HTTP API (enforced at server startup in app.main
# and per-request in app.auth). Left optional at import time so the CLI
# (app.cli) and subprocess workers can run without it.
API_TOKEN = os.environ.get("SCRAPI_API_TOKEN", "")
SCRAPI_BASE_URL = os.environ.get("SCRAPI_BASE_URL", "http://localhost:10700").rstrip("/")

FETCH_TIMEOUT_MS = int(os.environ.get("SCRAPI_FETCH_TIMEOUT_MS", "30000"))

# Cap on concurrent browser-based provider fetches (cloak Chromium
# instances). Each one is ~500 MB RAM; 2 is the right cap for this host.
BROWSER_MAX_CONCURRENT = int(os.environ.get("BROWSER_MAX_CONCURRENT", "2"))
BROWSER_MAX_REQUESTS_PER_WORKER = int(os.environ.get("BROWSER_MAX_REQUESTS_PER_WORKER", "100"))

# Hard asyncio timeout per provider call (seconds). Safety net that kills a
# provider attempt if its browser or HTTP call hangs past its own timeout.
PROVIDER_HARD_TIMEOUT_S = int(os.environ.get("PROVIDER_HARD_TIMEOUT_S", "45"))

# Hard asyncio timeout for the entire fetch_single_url call (all providers
# combined, including retries). Prevents a single URL from blocking forever.
FETCH_SINGLE_URL_TIMEOUT_S = int(os.environ.get("FETCH_SINGLE_URL_TIMEOUT_S", "120"))

PDF_MAX_CONCURRENT = int(os.environ.get("PDF_MAX_CONCURRENT", "1"))
PDF_RENDER_TIMEOUT_MS = int(os.environ.get("PDF_RENDER_TIMEOUT_MS", "45000"))

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"
FIRECRAWL_TIMEOUT_SECONDS = int(os.environ.get("FIRECRAWL_TIMEOUT_SECONDS", "30"))

PROXY_URL = os.environ.get("PROXY_URL", "")

# Browser-action engine (actions endpoint). Stateless: the caller passes the
# browser identity (cookies + UA) inline in the request — no store, no volume.
ACTION_MAX_CONCURRENT = int(os.environ.get("ACTION_MAX_CONCURRENT", "1"))
ACTION_RENDER_TIMEOUT_MS = int(os.environ.get("ACTION_RENDER_TIMEOUT_MS", "90000"))
