import pytest

from app.action_runner import ActionRequest, MediaItem
from tests.conftest import AUTH_HEADER

SESSION = {
    "cookies": [{"name": "auth_token", "value": "secret", "domain": ".x.com"}],
    "user_agent": "Mozilla/5.0",
}


def _action(**overrides):
    body = {
        "session": SESSION,
        "url": "https://x.com/compose/post",
        "recipe": "x_post",
        "params": {"text": "hello", "dry_run": True},
    }
    body.update(overrides)
    return body


# ── auth ───────────────────────────────────────────────────────────────────


def test_actions_requires_auth(client):
    resp = client.post("/api/v1/actions", json=_action())
    assert resp.status_code in (401, 403)


def test_actions_rejects_bad_token(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(),
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_actions_accepts_api_token(client):
    body = _action()
    del body["session"]
    resp = client.post("/api/v1/actions", json=body, headers=AUTH_HEADER)
    assert resp.status_code == 422


# ── request validation (errors before any browser spawns) ───────────────────


def test_missing_session_rejected(client):
    body = _action()
    del body["session"]
    resp = client.post("/api/v1/actions", json=body, headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_session_without_cookies_rejected(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(session={"cookies": []}),
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 422


def test_recipe_and_script_mutually_exclusive(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(script="() => 1"),  # recipe + script
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 422


def test_neither_recipe_nor_script_rejected(client):
    body = _action()
    del body["recipe"]
    resp = client.post("/api/v1/actions", json=body, headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_non_http_url_rejected(client):
    resp = client.post("/api/v1/actions", json=_action(url="ftp://x.com"), headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_too_much_media_rejected(client):
    media = [{"url": f"https://example.com/{i}.png"} for i in range(5)]
    resp = client.post("/api/v1/actions", json=_action(media=media), headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_x_post_params_rejected_before_browser(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(params={"dry_run": True}),
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 422


def test_x_post_rejects_extra_params(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(params={"text": "hello", "dry_run": True, "unknown": "nope"}),
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 422


# ── model-level ─────────────────────────────────────────────────────────────


def test_media_item_needs_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        MediaItem.model_validate({"data_base64": "AA==", "url": "https://x/y.png"})
    with pytest.raises(ValueError, match="exactly one"):
        MediaItem.model_validate({})


def test_action_request_valid_recipe():
    req = ActionRequest.model_validate(_action())
    assert req.recipe == "x_post"
    assert req.script is None
    assert req.session.cookies[0].name == "auth_token"
    assert req.params["dry_run"] is True


def test_x_post_accepts_long_form_text_before_browser():
    req = ActionRequest.model_validate(_action(params={"text": "x" * 281, "dry_run": True}))

    assert req.params["text"] == "x" * 281


def test_x_post_rejects_extreme_text_before_browser(client):
    resp = client.post(
        "/api/v1/actions",
        json=_action(params={"text": "x" * 25_001, "dry_run": True}),
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 422
