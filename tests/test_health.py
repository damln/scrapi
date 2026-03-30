def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.text == "ok"
