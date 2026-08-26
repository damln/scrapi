from app import action_runner, browser_capture, fetcher, pdf_renderer
from app.browser_budget import browser_slot


def test_all_browser_features_share_one_budget():
    assert fetcher.browser_slot is browser_slot
    assert action_runner.browser_slot is browser_slot
    assert pdf_renderer.browser_slot is browser_slot
    assert browser_capture.browser_slot is browser_slot
