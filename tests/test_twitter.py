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


# ---------------------------------------------------------------------------
# fxtwitter — head_meta
# ---------------------------------------------------------------------------


@respx.mock
def test_fxtwitter_head_meta_title(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["head_meta"]["title"] == "Test User: Hello from Twitter! Check this out."
    assert result["head_meta"]["og:title"] == "Test User: Hello from Twitter! Check this out."


@respx.mock
def test_fxtwitter_head_meta_description(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["head_meta"]["description"] == "Hello from Twitter! Check this out."
    assert result["head_meta"]["og:description"] == "Hello from Twitter! Check this out."


@respx.mock
def test_fxtwitter_head_meta_author(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["head_meta"]["author"] == "Test User"
    assert result["head_meta"]["twitter:creator"] == "@testuser"


@respx.mock
def test_fxtwitter_head_meta_og_fields(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["og:site_name"] == "X (formerly Twitter)"
    assert meta["og:type"] == "article"
    assert meta["og:url"] == "https://x.com/testuser/status/123456"
    assert meta["og:image"] == "https://pbs.twimg.com/media/photo1.jpg"


# ---------------------------------------------------------------------------
# fxtwitter — html + markdown + provider
# ---------------------------------------------------------------------------


@respx.mock
def test_fxtwitter_success(client):
    respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
    assert "Test User" in result["html"]
    assert "Hello from Twitter" in result["html"]
    assert "markdown" in result
    assert "Hello from Twitter" in result["markdown"]


@respx.mock
def test_fxtwitter_media_images(client):
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
def test_fxtwitter_stats(client):
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


# ---------------------------------------------------------------------------
# fxtwitter — article content
# ---------------------------------------------------------------------------


@respx.mock
def test_fxtwitter_article_html(client):
    respx.get("https://api.fxtwitter.com/writer/status/789").mock(
        return_value=Response(200, json=FXTWITTER_ARTICLE_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/writer/status/789"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert "<article>" in result["html"]
    assert "<h1>Introduction</h1>" in result["html"]
    assert "This is the article body." in result["html"]


@respx.mock
def test_fxtwitter_article_head_meta(client):
    respx.get("https://api.fxtwitter.com/writer/status/789").mock(
        return_value=Response(200, json=FXTWITTER_ARTICLE_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/writer/status/789"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["og:image"] == "https://pbs.twimg.com/cover.jpg"
    assert "Writer" in meta["title"]
    assert "My Long Article Title" in meta["title"]


# ---------------------------------------------------------------------------
# oEmbed fallback — head_meta
# ---------------------------------------------------------------------------


@respx.mock
def test_oembed_head_meta_title(client):
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

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["title"] == "OEmbed Author: Fallback tweet text here"
    assert meta["og:title"] == "OEmbed Author: Fallback tweet text here"


@respx.mock
def test_oembed_head_meta_description(client):
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

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["description"] == "Fallback tweet text here"
    assert meta["og:description"] == "Fallback tweet text here"


@respx.mock
def test_oembed_head_meta_author(client):
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

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["author"] == "OEmbed Author"
    assert meta["og:site_name"] == "X (formerly Twitter)"


@respx.mock
def test_oembed_html_and_provider(client):
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

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
    assert "OEmbed Author" in result["html"]
    assert "Fallback tweet text here" in result["html"]
    assert "markdown" in result


# ---------------------------------------------------------------------------
# Fallback to provider chain
# ---------------------------------------------------------------------------


@respx.mock
def test_both_strategies_fail_falls_through_to_providers(client):
    respx.get("https://api.fxtwitter.com/nobody/status/000").mock(
        return_value=Response(404)
    )
    respx.get("https://publish.twitter.com/oembed").mock(
        return_value=Response(404)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/nobody/status/000"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "error"
    assert result["provider"] == "twitter"
    assert result["error"] == "Not found (404)"
    assert result["html"] is None


# ---------------------------------------------------------------------------
# URL variants
# ---------------------------------------------------------------------------


@respx.mock
def test_twitter_com_domain(client):
    respx.get("https://api.fxtwitter.com/user/status/111").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://twitter.com/user/status/111"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"


@respx.mock
def test_www_x_com_domain(client):
    respx.get("https://api.fxtwitter.com/user/status/222").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.x.com/user/status/222"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
