from app.url_cleaner import clean_url


def test_strips_utm_params():
    result = clean_url("https://example.com/page?utm_source=google&color=red")
    assert "utm_source" not in result
    assert "color=red" in result


def test_preserves_params_order():
    result = clean_url("https://example.com/page?z=1&a=2")
    assert "z=1" in result
    assert "a=2" in result


def test_no_params_unchanged():
    result = clean_url("https://example.com/page")
    assert result == "https://example.com/page"


def test_strips_fbclid():
    result = clean_url("https://example.com/page?fbclid=abc123&q=search")
    assert "fbclid" not in result
    assert "q=search" in result
