import os

# Required to serve the HTTP API (enforced at server startup in app.main
# and per-request in app.auth). Left optional at import time so the CLI
# (app.cli) and subprocess workers can run without it.
API_TOKEN = os.environ.get("SCRAPI_API_TOKEN", "")
SCRAPI_BASE_URL = os.environ.get("SCRAPI_BASE_URL", "http://localhost:10700").rstrip("/")

FETCH_TIMEOUT_MS = int(os.environ.get("SCRAPI_FETCH_TIMEOUT_MS", "30000"))

# Each concurrent Chromium instance uses ~500 MB RAM.
BROWSER_MAX_CONCURRENT = int(os.environ.get("BROWSER_MAX_CONCURRENT", "2"))
BROWSER_MAX_REQUESTS_PER_WORKER = int(os.environ.get("BROWSER_MAX_REQUESTS_PER_WORKER", "100"))

PROVIDER_HARD_TIMEOUT_S = int(os.environ.get("PROVIDER_HARD_TIMEOUT_S", "45"))

FETCH_SINGLE_URL_TIMEOUT_S = int(os.environ.get("FETCH_SINGLE_URL_TIMEOUT_S", "120"))

PDF_MAX_CONCURRENT = int(os.environ.get("PDF_MAX_CONCURRENT", "1"))
PDF_RENDER_TIMEOUT_MS = int(os.environ.get("PDF_RENDER_TIMEOUT_MS", "45000"))

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"
FIRECRAWL_TIMEOUT_SECONDS = int(os.environ.get("FIRECRAWL_TIMEOUT_SECONDS", "30"))

PROXY_URL = os.environ.get("PROXY_URL", "")
CHATGPT_SESSION_FILE = os.environ.get("SCRAPI_CHATGPT_SESSION_FILE", "")

ACTION_MAX_CONCURRENT = int(os.environ.get("ACTION_MAX_CONCURRENT", "1"))
ACTION_RENDER_TIMEOUT_MS = int(os.environ.get("ACTION_RENDER_TIMEOUT_MS", "90000"))
