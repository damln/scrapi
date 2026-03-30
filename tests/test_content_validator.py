from app.content_validator import validate_content


def test_valid_html():
    html = "<html><body><p>Hello world, this is a valid page with enough content to pass the length check.</p>" + "x" * 200 + "</body></html>"
    result = validate_content(html)
    assert result["valid"] is True


def test_too_short():
    html = "<html><body><p>Hi</p></body></html>"
    result = validate_content(html)
    assert result["valid"] is False
    assert "short" in result["reason"].lower() or "length" in result["reason"].lower()


def test_no_body():
    html = "x" * 300
    result = validate_content(html)
    assert result["valid"] is False


def test_blocked_content():
    html = "<html><body>" + "x" * 300 + "Access Denied. Please enable cookies. Captcha required.</body></html>"
    result = validate_content(html)
    assert result["valid"] is False
    assert result["scores"]["blocked_matches"]
