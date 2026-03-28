"""Cookie consent popup dismissal via cosmetic filters + MutationObserver."""

from pathlib import Path

_DIR = Path(__file__).parent
_CSS = (_DIR / "cosmetic_filters.css").read_text()
_JS = (_DIR / "observer.js").read_text()

FALLBACK_SELECTORS = [
    '#onetrust-accept-btn-handler',
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    '.cmp-intro_acceptAll',
    '.cc-btn.cc-allow',
    '[data-testid="cookie-accept"]',
    'button[aria-label*="accept" i]',
    'button[aria-label*="agree" i]',
    'button[aria-label*="consent" i]',
]

FALLBACK_REMOVE_JS = """
document.querySelectorAll(
    '#cookie-banner, #cookieModal, .cookie-consent, ' +
    '#onetrust-banner-sdk, .cc-window, #gdpr-consent, ' +
    '.modal-backdrop, [class*="cookie-banner"], ' +
    '[id*="consent-banner"], [id*="cookie-policy"]'
).forEach(el => el.remove());
document.body.style.overflow = '';
document.documentElement.style.overflow = '';
"""


def dismiss_cookies(page):
    """Inject cosmetic filters and observer to hide/remove cookie banners.

    Runs as a StealthyFetcher page_action callback (sync).
    Must return the page object.
    """
    # 1. Inject CSS cosmetic filters (hides most banners instantly)
    page.add_style_tag(content=_CSS)

    # 2. Inject MutationObserver JS (handles dynamically injected banners)
    page.evaluate(_JS)
    page.wait_for_timeout(500)

    # 3. Fallback: try clicking known accept buttons
    for selector in FALLBACK_SELECTORS:
        try:
            locator = page.locator(selector)
            if locator.first.is_visible(timeout=300):
                locator.first.click(timeout=500)
                page.wait_for_timeout(300)
                break
        except Exception:
            continue

    # 4. Last resort: force-remove known banner elements
    page.evaluate(FALLBACK_REMOVE_JS)

    return page
