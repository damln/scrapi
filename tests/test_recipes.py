from app.recipes import RECIPE_PARAM_MODELS, RECIPES
from app.recipes.twitter import CREATE_TWEET_RE, _rest_id_from_payload


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
