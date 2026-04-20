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


# ---------------------------------------------------------------------------
# Outgoing request: browser UA (Cloudflare in front of fxtwitter 403s the
# default httpx UA, which caused every article tweet to silently degrade to
# the oEmbed stub — see twitter_fetcher.py comment).
# ---------------------------------------------------------------------------


@respx.mock
def test_fxtwitter_sends_browser_user_agent(client):
    route = respx.get("https://api.fxtwitter.com/testuser/status/123456").mock(
        return_value=Response(200, json=FXTWITTER_RESPONSE)
    )

    client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/testuser/status/123456"},
        headers=AUTH_HEADER,
    )

    assert route.called
    ua = route.calls.last.request.headers.get("user-agent", "")
    assert "python-httpx" not in ua.lower()
    assert "Mozilla/5.0" in ua


# ---------------------------------------------------------------------------
# Thread reconstruction: fxtwitter gives us `replying_to_status` — we walk
# it to include the parent conversation in the output so a bare-link reply
# (like https://x.com/gregpr07/status/2045566284319134008) surfaces the
# original announcement instead of just the t.co URL.
# ---------------------------------------------------------------------------


LEAF_REPLY_RESPONSE = {
    "tweet": {
        "id": "2045566284319134008",
        "text": "github.com/browser-use/browser-harness",
        "created_at": "Sat Apr 18 18:13:01 +0000 2026",
        "author": {"name": "Gregor Zunic", "screen_name": "gregpr07", "avatar_url": ""},
        "replying_to": "gregpr07",
        "replying_to_status": "2045566281991311483",
        "views": 34306,
        "likes": 373,
        "retweets": 9,
    }
}

PARENT_ANNOUNCEMENT_RESPONSE = {
    "tweet": {
        "id": "2045566281991311483",
        "text": "Introducing: Browser Harness. A self-healing harness that can complete virtually any browser task.",
        "created_at": "Sat Apr 18 18:12:55 +0000 2026",
        "author": {"name": "Gregor Zunic", "screen_name": "gregpr07", "avatar_url": ""},
    }
}


@respx.mock
def test_fxtwitter_walks_thread_parent(client):
    respx.get("https://api.fxtwitter.com/gregpr07/status/2045566284319134008").mock(
        return_value=Response(200, json=LEAF_REPLY_RESPONSE)
    )
    parent_route = respx.get("https://api.fxtwitter.com/_/status/2045566281991311483").mock(
        return_value=Response(200, json=PARENT_ANNOUNCEMENT_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/gregpr07/status/2045566284319134008"},
        headers=AUTH_HEADER,
    )

    assert parent_route.called, "parent tweet must be fetched when replying_to_status is set"
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert "Introducing: Browser Harness" in result["html"]
    assert "thread-ancestor" in result["html"]
    # Parent content should also reach the markdown conversion path.
    assert "Introducing: Browser Harness" in (result.get("markdown") or "")


@respx.mock
def test_fxtwitter_title_falls_back_to_root_when_leaf_is_bare_link(client):
    """Leaf text is just a t.co link; title should come from the root parent."""
    respx.get("https://api.fxtwitter.com/gregpr07/status/2045566284319134008").mock(
        return_value=Response(200, json={
            "tweet": {
                **LEAF_REPLY_RESPONSE["tweet"],
                "text": "https://t.co/abc",
            }
        })
    )
    respx.get("https://api.fxtwitter.com/_/status/2045566281991311483").mock(
        return_value=Response(200, json=PARENT_ANNOUNCEMENT_RESPONSE)
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/gregpr07/status/2045566284319134008"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert "Browser Harness" in result["head_meta"]["title"]


@respx.mock
def test_fxtwitter_thread_walk_stops_at_cycle(client):
    """Defensive: a parent that points at the leaf must not trigger an infinite
    fetch loop — we dedupe by tweet id in the walker."""
    leaf = {
        "tweet": {
            "id": "100",
            "text": "leaf",
            "author": {"name": "A", "screen_name": "a"},
            "replying_to_status": "200",
        }
    }
    # Parent's replying_to_status cycles back to the leaf.
    parent = {
        "tweet": {
            "id": "200",
            "text": "parent",
            "author": {"name": "B", "screen_name": "b"},
            "replying_to_status": "100",
        }
    }
    respx.get("https://api.fxtwitter.com/a/status/100").mock(
        return_value=Response(200, json=leaf)
    )
    parent_route = respx.get("https://api.fxtwitter.com/_/status/200").mock(
        return_value=Response(200, json=parent)
    )
    # The loop-back fetch for the leaf must NOT happen — the walker sees id 100
    # in the seen-set and stops.
    loop_route = respx.get("https://api.fxtwitter.com/_/status/100").mock(
        return_value=Response(200, json=leaf)
    )

    client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/a/status/100"},
        headers=AUTH_HEADER,
    )

    assert parent_route.called
    assert not loop_route.called


# ---------------------------------------------------------------------------
# Quote tweet (QRT) rendering
# ---------------------------------------------------------------------------


@respx.mock
def test_fxtwitter_quoted_tweet_rendered(client):
    respx.get("https://api.fxtwitter.com/user/status/500").mock(
        return_value=Response(200, json={
            "tweet": {
                "id": "500",
                "text": "Worth reading:",
                "author": {"name": "Reader", "screen_name": "reader"},
                "quote": {
                    "id": "499",
                    "text": "A spicy take that deserves a boost.",
                    "author": {"name": "Original", "screen_name": "original"},
                },
            }
        })
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/user/status/500"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert "quoted-tweet" in result["html"]
    assert "A spicy take that deserves a boost" in result["html"]
    assert "@original" in result["html"]


# ---------------------------------------------------------------------------
# Syndication fallback (tertiary, after fxtwitter + oEmbed both fail)
# ---------------------------------------------------------------------------


@respx.mock
def test_syndication_fallback_when_fxtwitter_and_oembed_fail(client):
    # fxtwitter down
    respx.get("https://api.fxtwitter.com/user/status/777").mock(
        return_value=Response(500, text="boom")
    )
    # oEmbed down
    respx.get("https://publish.twitter.com/oembed").mock(
        return_value=Response(500, text="boom")
    )
    # syndication works, returns text + article preview
    synd_route = respx.get("https://cdn.syndication.twimg.com/tweet-result").mock(
        return_value=Response(200, json={
            "text": "Hello from syndication",
            "created_at": "2026-04-19T20:09:22.000Z",
            "user": {"name": "Syn Author", "screen_name": "synauthor"},
            "article": {"title": "Fallback Title", "preview_text": "A short preview."},
        })
    )

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://x.com/user/status/777"},
        headers=AUTH_HEADER,
    )

    assert synd_route.called
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "twitter"
    assert "Hello from syndication" in result["html"]
    assert "Fallback Title" in result["html"]
    assert "A short preview" in result["html"]
