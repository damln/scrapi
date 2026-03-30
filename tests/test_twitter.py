import respx
from httpx import Response

from tests.conftest import AUTH_HEADER

FXTWITTER_RESPONSE = {
    "tweet": {
        "text": "Hello from Twitter! Check this out.",
        "created_at": "2024-01-15T12:00:00Z",
        "views": 1500,
        "likes": 42,
        "retweets": 7,
        "author": {
            "name": "Test User",
            "screen_name": "testuser",
            "avatar_url": "https://pbs.twimg.com/avatar.jpg",
        },
        "media": {
            "photos": [
                {"url": "https://pbs.twimg.com/media/photo1.jpg"},
            ],
        },
    }
}

FXTWITTER_ARTICLE_RESPONSE = {
    "tweet": {
        "text": "https://t.co/abc123",
        "created_at": "2024-01-15T12:00:00Z",
        "views": 5000,
        "likes": 200,
        "retweets": 50,
        "author": {
            "name": "Writer",
            "screen_name": "writer",
            "avatar_url": "https://pbs.twimg.com/avatar2.jpg",
        },
        "article": {
            "title": "My Long Article Title",
            "content": {
                "blocks": [
                    {"type": "header-one", "text": "Introduction"},
                    {"type": "unstyled", "text": "This is the article body."},
                    {"type": "atomic", "text": ""},
                    {"type": "unstyled", "text": "Second paragraph."},
                ],
            },
            "cover_media": {
                "media_info": {
                    "original_img_url": "https://pbs.twimg.com/cover.jpg",
                },
            },
        },
    }
}

OEMBED_RESPONSE = {
    "html": '<blockquote><p>Fallback tweet text here</p></blockquote>',
    "author_name": "OEmbed Author",
}


@respx.mock
def test_twitter_fxtwitter_success(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    data = resp.json()
    result = data["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
    assert "Test User" in result["html"]
    assert "Hello from Twitter" in result["html"]
    assert result["head_meta"]["title"] == "Test User: Hello from Twitter! Check this out."
    assert result["head_meta"]["og:type"] == "article"
    assert "markdown" in result
    assert "Hello from Twitter" in result["markdown"]


@respx.mock
def test_twitter_article_content(client):
    respx.get("https://api.fxtwitter.com/writer/status/789").mock(
        return_value=Response(200, json=FXTWITTER_ARTICLE_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/writer/status/789"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert "<article>" in result["html"]
    assert "<h1>Introduction</h1>" in result["html"]
    assert "This is the article body." in result["html"]
    assert result["head_meta"]["og:image"] == "https://pbs.twimg.com/cover.jpg"


@respx.mock
def test_twitter_fxtwitter_fails_falls_back_to_oembed(client):
    respx.get("https://api.fxtwitter.com/fallback/status/999").mock(
        return_value=Response(500)
    )
    respx.get("https://publish.twitter.com/oembed").mock(
        return_value=Response(200, json=OEMBED_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/fallback/status/999"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
    assert "OEmbed Author" in result["html"]
    assert "Fallback tweet text here" in result["html"]


@respx.mock
def test_twitter_both_strategies_fail_falls_through_to_providers(client):
    respx.get("https://api.fxtwitter.com/nobody/status/000").mock(
        return_value=Response(404)
    )
    respx.get("https://publish.twitter.com/oembed").mock(
        return_value=Response(404)
    )
    # After twitter fetcher fails, falls through to the normal provider chain
    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/nobody/status/000"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    # Provider chain may succeed (real browser) or fail — just check it's not "twitter" provider
    if result["status"] == "success":
        assert result["provider"] != "twitter"


@respx.mock
def test_twitter_media_images(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert "photo1.jpg" in result["html"]


@respx.mock
def test_twitter_stats(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert "1500 views" in result["html"]
    assert "42 likes" in result["html"]
    assert "7 retweets" in result["html"]
