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
    # This will fail at the fetch level but auth should pass
    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://example.com"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
