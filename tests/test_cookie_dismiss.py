from pathlib import Path

from app.cookie_dismiss.filter_parser import build_observer_js


def test_observer_reuses_css_rules_without_embedding_selector_catalogue():
    observer = build_observer_js(["#cookie-banner", ".consent-modal"])

    assert "#cookie-banner" not in observer
    assert ".consent-modal" not in observer
    assert "document.styleSheets" in observer
    assert "mutation.addedNodes" in observer
    assert "setTimeout(flush, 50)" in observer


def test_bundled_observer_matches_generator():
    observer_path = Path(__file__).parents[1] / "app" / "cookie_dismiss" / "observer.js"
    assert observer_path.read_text() == build_observer_js([])
