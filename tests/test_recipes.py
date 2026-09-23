from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.recipes import RECIPE_PARAM_MODELS, RECIPES
from app.recipes.twitter import CREATE_TWEET_RE, _dismiss_composer_suggestions, _rest_id_from_payload, x_post


def test_dismiss_composer_suggestions():
    page, editor = MagicMock(), MagicMock()
    editor.get_attribute.return_value = "typeaheadDropdownWrapped-1"
    log = []

    _dismiss_composer_suggestions(page, editor, 5000, log)

    page.locator.assert_called_once_with('[id="typeaheadDropdownWrapped-1"][role="listbox"]')
    page.keyboard.press.assert_called_once_with("Escape")
    editor.press.assert_not_called()
    page.locator.return_value.wait_for.assert_called_once_with(state="hidden", timeout=5000)
    assert log == ["dismissed composer suggestions"]


@pytest.mark.parametrize("controls", [None, "typeaheadDropdownWrapped-1"])
def test_no_escape_without_visible_suggestions(controls):
    page, editor = MagicMock(), MagicMock()
    editor.get_attribute.return_value = controls
    page.locator.return_value.is_visible.return_value = False

    _dismiss_composer_suggestions(page, editor, 5000, [])

    editor.press.assert_not_called()
    page.keyboard.press.assert_not_called()


def test_dismiss_failure_stops_composing():
    page, editor = MagicMock(), MagicMock()
    editor.get_attribute.return_value = "typeaheadDropdownWrapped-1"
    page.locator.return_value.wait_for.side_effect = PlaywrightTimeoutError("still open")

    with pytest.raises(PlaywrightTimeoutError, match="still open"):
        _dismiss_composer_suggestions(page, editor, 5000, [])


def test_dry_run_dismisses_suggestions_for_each_thread_entry(monkeypatch):
    page = MagicMock()
    dismiss = MagicMock()
    monkeypatch.setattr("app.recipes.twitter._dismiss_composer_suggestions", dismiss)
    text = "https://example.com/#hero"
    req = {"timeout_ms": 5000, "params": {"text": text, "thread": ["@example"], "dry_run": True}}

    result = x_post(page, req, [])

    assert result == {"posted": False, "dry_run": True, "tweets": 2}
    assert dismiss.call_count == 2
    assert dismiss.call_args_list[0].args[1] is page.locator.return_value.first
    assert dismiss.call_args_list[1].args[1] is page.locator.return_value.last
    assert [call.args[0] for call in page.keyboard.insert_text.call_args_list] == [text, "@example"]
    page.expect_response.assert_not_called()


def test_x_post_registered():
    assert "x_post" in RECIPES
    assert callable(RECIPES["x_post"])
    assert "x_post" in RECIPE_PARAM_MODELS


def test_rest_id_from_create_tweet_payload():
    payload = {"data": {"create_tweet": {"tweet_results": {"result": {"rest_id": "1799999999999999999"}}}}}
    assert _rest_id_from_payload(payload) == "1799999999999999999"


def test_rest_id_falls_back_to_legacy_id_str():
    payload = {"data": {"create_tweet": {"tweet_results": {"result": {"legacy": {"id_str": "1788888888888888888"}}}}}}
    assert _rest_id_from_payload(payload) == "1788888888888888888"


def test_rest_id_from_note_tweet_payload():
    payload = {"data": {"notetweet_create": {"tweet_results": {"result": {"rest_id": "1777777777777777777"}}}}}
    assert _rest_id_from_payload(payload) == "1777777777777777777"


def test_rest_id_returns_none_for_unexpected_shapes():
    assert _rest_id_from_payload(None) is None
    assert _rest_id_from_payload({}) is None
    assert _rest_id_from_payload({"data": {"create_tweet": {}}}) is None
    assert _rest_id_from_payload({"errors": [{"message": "denied"}]}) is None


def test_create_tweet_regex_matches_graphql_urls():
    assert CREATE_TWEET_RE.search("https://x.com/i/api/graphql/aBcD123/CreateTweet")
    assert CREATE_TWEET_RE.search("https://x.com/i/api/graphql/xYz/CreateNoteTweet")
    assert not CREATE_TWEET_RE.search("https://x.com/i/api/graphql/aBcD123/FavoriteTweet")


def test_recipe_names_match_request_literal():
    # The ActionRequest.recipe Literal must list exactly the registered recipes.
    import typing

    from app.action_runner import ActionRequest

    field = ActionRequest.model_fields["recipe"]
    # annotation is `Literal[...] | None`
    literal_args = set()
    for arg in typing.get_args(field.annotation):
        literal_args.update(typing.get_args(arg))
    assert literal_args == set(RECIPES)
