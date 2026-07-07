"""Tests for app.ad_blocker — Playwright route handler that abort()s
requests to known ad/tracker hosts for the cloak provider.
"""

from unittest.mock import MagicMock

from app.ad_blocker import (
    _LEGACY_HOST_DENYLIST,
    BLOCKED_HOSTS,
    block_ads,
    is_blocked,
)


class TestIsBlocked:
    def test_matches_doubleclick(self):
        assert is_blocked("https://ad.doubleclick.net/ads/12345")

    def test_matches_google_analytics(self):
        assert is_blocked("https://www.google-analytics.com/g/collect")

    def test_matches_facebook_pixel(self):
        assert is_blocked("https://connect.facebook.net/en_US/fbevents.js")

    def test_matches_hotjar(self):
        assert is_blocked("https://static.hotjar.com/c/hotjar-12345.js")

    def test_does_not_match_real_content(self):
        assert not is_blocked("https://en.wikipedia.org/wiki/Web_scraping")
        assert not is_blocked("https://www.coches.net/segunda-mano/")
        assert not is_blocked("https://www.lemonde.fr/economie/")


class TestSubdomainChain:
    def test_subdomain_of_listed_base_is_blocked(self):
        # `doubleclick.net` is in the legacy list -> any subdomain blocks
        assert is_blocked("https://anything.doubleclick.net/")
        assert is_blocked("https://deep.subdomain.tree.doubleclick.net/x?a=1")

    def test_sibling_host_is_not_blocked(self):
        # facebook.net is in the list; facebook.com is NOT (and shouldn't
        # be — it's the user-facing site, not a tracker host)
        assert is_blocked("https://connect.facebook.net/tr")
        assert not is_blocked("https://www.facebook.com/some/post")

    def test_path_pattern_still_matched(self):
        # `yandex.ru/metrika` is in the small path-pattern set —
        # substring-matched against the URL regardless of host parse.
        assert is_blocked("https://mc.yandex.ru/metrika/tag.js")


class TestBlockAds:
    def test_aborts_blocked_request(self):
        route = MagicMock()
        route.request.url = "https://www.googletagmanager.com/gtag/js?id=GTM-XXXX"
        block_ads(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_continues_normal_request(self):
        route = MagicMock()
        route.request.url = "https://en.wikipedia.org/wiki/Web_scraping"
        block_ads(route)
        route.continue_.assert_called_once()
        route.abort.assert_not_called()


def test_blocked_hosts_is_non_trivial():
    # Either we loaded the bundled StevenBlack file (~80K hosts) or we
    # fell back to the legacy 50-host list — both are real denylists.
    assert len(BLOCKED_HOSTS) >= 30
    assert "doubleclick.net" in BLOCKED_HOSTS
    assert "google-analytics.com" in BLOCKED_HOSTS


def test_legacy_host_denylist_intact():
    # Sanity: the legacy fallback covers the high-signal core hosts so
    # ad_blocker still works on dev environments without a rebuilt image.
    assert "doubleclick.net" in _LEGACY_HOST_DENYLIST
    assert "connect.facebook.net" in _LEGACY_HOST_DENYLIST
