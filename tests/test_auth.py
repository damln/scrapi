import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import AUTH_HEADER


def test_content_requires_auth(client):
    resp = client.get("/api/v1/content", params={"urls": "https://example.com"})
    assert resp.status_code in (401, 403)


def test_content_rejects_bad_token(client):
    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code in (401, 403)


def test_content_accepts_valid_token(client):
    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("client_host", "base_url"),
    [
        ("127.0.0.1", "http://localhost:10700"),
        ("127.0.0.1", "http://127.0.0.1:10700"),
        ("::1", "http://localhost:10700"),
        ("172.17.0.2", "http://host.docker.internal:10700"),
        ("172.18.0.1", "http://172.18.0.2:10700"),
        ("192.168.65.1", "http://127.0.0.1:10700"),
    ],
)
def test_local_requests_do_not_require_auth(client_host, base_url):
    with TestClient(app, client=(client_host, 50000), base_url=base_url) as local_client:
        resp = local_client.get("/api/v1/content")

    assert resp.status_code == 422


def test_remote_request_cannot_bypass_auth_with_local_host():
    with TestClient(app, client=("203.0.113.10", 50000), base_url="http://localhost:10700") as remote_client:
        resp = remote_client.get("/api/v1/content")

    assert resp.status_code == 401


def test_reverse_proxy_peer_still_requires_auth_for_public_host():
    with TestClient(app, client=("172.18.0.2", 50000), base_url="https://scrapi.example.com") as proxy_client:
        resp = proxy_client.get("/api/v1/content")

    assert resp.status_code == 401
