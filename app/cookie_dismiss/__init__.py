"""Cookie consent popup dismissal via cosmetic filters + MutationObserver."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent
_CSS = (_DIR / "cosmetic_filters.css").read_text()
_JS = (_DIR / "observer.js").read_text()

FALLBACK_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".cmp-intro_acceptAll",
    ".cc-btn.cc-allow",
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

# Remove every element our cosmetic-filters stylesheet matched instead of
# leaving it hidden: DOM serialization and markdownify re-emit hidden text.
# Our stylesheet is identified by its alphabetically-first selector
# (`#-CookieConsentContainer`) so the site's own display:none rules are
# never walked.
COSMETIC_REMOVE_JS = """
(() => {
    const SIGNATURE = '#-CookieConsentContainer';
    let sheet = null;
    for (const s of document.styleSheets) {
        try {
            if (s.cssRules.length && s.cssRules[0].selectorText &&
                s.cssRules[0].selectorText.indexOf(SIGNATURE) !== -1) {
                sheet = s;
                break;
            }
        } catch (_) {}  // cross-origin sheets throw — skip
    }
    if (!sheet) return 0;
    let removed = 0;
    const walk = (rules) => {
        for (const rule of rules) {
            if (rule.cssRules) { walk(rule.cssRules); continue; }  // @media, @supports
            if (!rule.selectorText) continue;
            try {
                for (const el of document.querySelectorAll(rule.selectorText)) {
                    el.remove();
                    removed++;
                }
            } catch (_) {}  // bad / unsupported selector — skip
        }
    };
    walk(sheet.cssRules);
    return removed;
})();
"""


def dismiss_cookies(page):
    """Inject cosmetic filters and observer to hide/remove cookie banners."""
    # 1. Inject CSS cosmetic filters (hides most banners instantly)
    page.add_style_tag(content=_CSS)

    # 2. Inject MutationObserver JS (handles dynamically injected banners)
    page.evaluate(_JS)
    page.wait_for_timeout(500)

    # 3. Fallback: click a known accept button. One combined locator keeps
    # pages without a banner fast.
    try:
        combined = ", ".join(FALLBACK_SELECTORS)
        locator = page.locator(combined).first
        if locator.is_visible(timeout=300):
            locator.click(timeout=500)
            page.wait_for_timeout(300)
    except Exception as exc:
        logger.debug("Cookie-banner click failed: %s", exc)

    # 4. Remove elements matched by our cosmetic filters.
    page.evaluate(COSMETIC_REMOVE_JS)

    # 5. Last resort: force-remove known banner elements not covered by
    # the cosmetic stylesheet (generic fallback selectors).
    page.evaluate(FALLBACK_REMOVE_JS)

    return page
