import os

# Set required env vars before importing the app (only if not already set)
os.environ.setdefault("SCRAPI_API_TOKEN", "test-token")

import pytest
from fastapi.testclient import TestClient

from app.cache import clear_cache
from app.config import API_TOKEN
from app.main import app


@pytest.fixture(autouse=True)
def _clear_cache_before_test():
    """Ensure no stale cache data leaks between tests."""
    clear_cache()
    yield


@pytest.fixture
def client():
    """Synchronous test client for the FastAPI app."""
    with TestClient(app) as c:
        yield c


AUTH_HEADER = {"Authorization": f"Bearer {API_TOKEN}"}
