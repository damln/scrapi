import os

API_TOKEN = os.environ["SCRAPI_API_TOKEN"]
FETCH_TIMEOUT_MS = int(os.environ.get("SCRAPI_FETCH_TIMEOUT_MS", "30000"))
