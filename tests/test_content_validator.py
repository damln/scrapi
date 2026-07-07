from app.content_validator import validate_content


def test_valid_html():
    html = (
        "<html><body><p>Hello world, this is a valid page with enough content to pass the length check.</p>"
        + "x" * 200
        + "</body></html>"
    )
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
    html = "<html><body>" + "x" * 300 + "Access Denied. Please enable JavaScript to continue.</body></html>"
    result = validate_content(html)
    assert result["valid"] is False
    assert result["scores"]["blocked_matches"]


# Hard block markers — single occurrence triggers fail, no need for >= 2


def test_datadome_challenge_page_is_blocked():
    # Real DataDome challenge body observed on leboncoin.fr/idealista.com
    # (~1.5 KB). The previous validator passed this as success because
    # only "captcha" was in the soft list and "captcha" alone was 1
    # match (needed >= 2). The hard marker `geo.captcha-delivery.com`
    # now catches it on the first occurrence.
    html = (
        '<html lang="en"><head><title>leboncoin.fr</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '</head><body style="margin:0">'
        + "x"
        * 300
        + '<iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=AHrlqAAA" '
        'title="DataDome CAPTCHA" width="100%"></iframe>'
        "</body></html>"
    )
    result = validate_content(html)
    assert result["valid"] is False
    assert "hard_block" in result["reason"]
    assert "geo.captcha-delivery.com" in result["scores"]["hard_block_matches"]


def test_cloudflare_managed_challenge_is_blocked():
    # cf-mitigated header / cf-chl-bypass token — Cloudflare bot
    # management interstitial. Doesn't appear in real content.
    html = (
        "<html><body>" + "x" * 300 + '<script>window._cf_chl_opt = {cvId: "3", cType: "managed"};</script>'
        '<input type="hidden" name="cf-chl-bypass" value="abc123">'
        "</body></html>"
    )
    result = validate_content(html)
    assert result["valid"] is False
    assert "hard_block" in result["reason"]


def test_coches_net_interruption_page_is_blocked():
    html = (
        "<html><body>"
        + "x" * 300
        + "<h1>Ups! Parece que algo no va bien</h1>"
        + '<div class="interruption-message">Verifica que eres humano</div>'
        + '<script src="https://js.hcaptcha.com/1/api.js"></script>'
        + "</body></html>"
    )
    result = validate_content(html)
    assert result["valid"] is False
    assert "hard_block" in result["reason"]
    assert "js.hcaptcha.com/1/api.js" in result["scores"]["hard_block_matches"]


def test_real_help_article_about_captchas_still_passes():
    # Negative case: a real article that mentions "captcha" multiple
    # times but isn't a challenge page. "captcha" is not in the soft
    # list (substring of recaptcha/hcaptcha — was tripping false
    # positives on Reddit etc.), so this scores 0 soft hits.
    html = (
        "<html><body>"
        + "x" * 500
        + "Help center article: how CAPTCHA works. "
        + "CAPTCHAs (Completely Automated Public Turing tests to tell "
        + "Computers and Humans Apart) are widely used. "
        + "</body></html>"
    )
    result = validate_content(html)
    assert result["valid"] is True


def test_reddit_thread_with_recaptcha_widget_passes():
    # Regression for the May 2026 Reddit archiver failure: every
    # reddit.com/r/<sub>/comments/<id>/ page ships a reCAPTCHA widget
    # for the sign-up flow, so the served HTML contains ~30 mentions
    # of "captcha" and ~15 of "recaptcha". Before the captcha-soft-list
    # cleanup, those counted as two distinct soft hits and the chain
    # validator rejected cloak's perfectly good 800 KB response,
    # falling through to firecrawl which also failed on the target host
    # stored scrapi_failed on every Reddit URL.
    html = (
        "<html><body>"
        + "x" * 500
        + (" reCAPTCHA " * 15)
        + (" captcha " * 18)
        + " Real Reddit thread content goes here. "
        + "</body></html>"
    )
    result = validate_content(html)
    assert result["valid"] is True, result
