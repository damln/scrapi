def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<title>Scrapi</title>" in resp.text
    assert 'href="/static/favicon.png"' in resp.text
    assert "radial-gradient" in resp.text
    assert "<script>" not in resp.text


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_status_without_proxy(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["proxy"]["configured"] is False
    assert body["proxy"]["url"] is None
    assert body["proxy"]["ok"] is True
    assert body["proxy"]["error"] is None
    assert "fetches run direct" in body["proxy"]["note"]


def test_status_direct_proxy_profile(client):
    resp = client.get("/status", params={"proxy_profile": "direct"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["proxy"]["profile"] == "direct"
    assert body["proxy"]["configured"] is False
    assert body["proxy"]["ok"] is True
    assert body["proxy"]["error"] is None


def test_api_status_without_proxy(client):
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    assert resp.json()["proxy"]["configured"] is False
