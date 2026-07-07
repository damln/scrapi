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

# Walk the cosmetic-filters stylesheet we just injected and physically
# remove every element it matched, instead of leaving them hidden via
# `display:none`. The browser has already parsed all 170 rules / tens
# of thousands of selectors in `cosmetic_filters.css` — we just iterate
# the parsed cssRules and call querySelectorAll + remove() per rule.
# Why this matters: markdownify (and any DOM serialization for that
# matter) re-emits hidden text. Hidden cookie walls were leaking into
# our markdown output. Removed elements can't.
# We identify our stylesheet by the alphabetically-first selector in
# the file (`#-CookieConsentContainer`) so we don't accidentally walk
# the site's own display:none rules (legit hidden tabs / dropdowns).
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
    """Inject cosmetic filters and observer to hide/remove cookie banners.

    Runs as a StealthyFetcher page_action callback (sync).
    Must return the page object.
    """
    # 1. Inject CSS cosmetic filters (hides most banners instantly)
    page.add_style_tag(content=_CSS)

    # 2. Inject MutationObserver JS (handles dynamically injected banners)
    page.evaluate(_JS)
    page.wait_for_timeout(500)

    # 3. Fallback: try clicking known accept buttons. Iterating one by one
    # with a 300ms timeout each cost up to 2.4s on pages with no banner at
    # all (forbes.com, news.ycombinator.com, etc.) — and on those pages
    # steps 1+2 already did the work. A single locator built from a CSS
    # selector group does the same job in one shot: if ANY of the buttons
    # is visible, click it; if none, fall through fast.
    try:
        combined = ", ".join(FALLBACK_SELECTORS)
        locator = page.locator(combined).first
        if locator.is_visible(timeout=300):
            locator.click(timeout=500)
            page.wait_for_timeout(300)
    except Exception as exc:
        logger.debug("Cookie-banner click failed: %s", exc)

    # 4. Walk our cosmetic-filters stylesheet and physically remove every
    # element it matched (not just hide via CSS). Removes the markdown
    # bloat that came from `display:none` cookie walls being serialized.
    page.evaluate(COSMETIC_REMOVE_JS)

    # 5. Last resort: force-remove known banner elements not covered by
    # the cosmetic stylesheet (generic fallback selectors).
    page.evaluate(FALLBACK_REMOVE_JS)

    return page
