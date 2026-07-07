import respx
from httpx import Response

from tests.conftest import AUTH_HEADER

OEMBED_RESPONSE = {
    "title": "Never Gonna Give You Up",
    "author_name": "Rick Astley",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "html": '<iframe width="480" height="270" src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>',
}


@respx.mock
def test_youtube_head_meta_title(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["title"] == "Never Gonna Give You Up — Rick Astley"
    assert meta["og:title"] == "Never Gonna Give You Up"


@respx.mock
def test_youtube_head_meta_og_fields(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["og:site_name"] == "YouTube"
    assert meta["og:type"] == "video"
    assert meta["og:url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert meta["og:image"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


@respx.mock
def test_youtube_head_meta_author(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["author"] == "Rick Astley"


@respx.mock
def test_youtube_success(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "youtube"
    assert "Never Gonna Give You Up" in result["html"]
    assert "Rick Astley" in result["html"]
    assert "markdown" in result


@respx.mock
def test_youtube_embed_html_in_body(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert "<iframe" in result["html"]
    assert "youtube.com/embed" in result["html"]


@respx.mock
def test_youtube_oembed_failure_falls_through(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(404))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=invalid"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "error"
    assert result["provider"] == "youtube"
    assert result["error"] == "Not found (404)"
    assert result["html"] is None


@respx.mock
def test_youtube_short_url(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://youtu.be/dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "youtube"
    assert result["head_meta"]["og:title"] == "Never Gonna Give You Up"


@respx.mock
def test_youtube_mobile_url(client):
    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=OEMBED_RESPONSE))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://m.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    result = resp.json()["results"][0]
    assert result["status"] == "success"
    assert result["provider"] == "youtube"
    assert result["head_meta"]["author"] == "Rick Astley"


@respx.mock
def test_youtube_title_with_no_author(client):
    response = {**OEMBED_RESPONSE, "author_name": ""}

    respx.get("https://www.youtube.com/oembed").mock(return_value=Response(200, json=response))

    resp = client.get(
        "/api/v1/content",
        params={"urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=AUTH_HEADER,
    )

    meta = resp.json()["results"][0]["head_meta"]
    assert meta["title"] == "Never Gonna Give You Up"
