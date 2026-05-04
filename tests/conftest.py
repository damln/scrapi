import os

# Set required env vars before importing the app (only if not already set)
os.environ.setdefault("SCRAPI_API_TOKEN", "test-token")

import pytest
from fastapi.testclient import TestClient

from app.config import API_TOKEN
from app.main import app


@pytest.fixture
def client():
    """Synchronous test client for the FastAPI app."""
    with TestClient(app) as c:
        yield c


AUTH_HEADER = {"Authorization": f"Bearer {API_TOKEN}"}
