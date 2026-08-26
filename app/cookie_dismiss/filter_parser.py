"""Parse AdBlock Plus / uBlock Origin filter lists and extract generic cosmetic (CSS) rules."""

import re


def extract_cosmetic_selectors(filter_text: str) -> list[str]:
    """Extract generic CSS element-hiding selectors from a filter list.

    Only keeps generic rules (lines starting with ##).
    Ignores domain-specific rules (domain##selector) and network rules.
    """
    selectors = set()

    for line in filter_text.splitlines():
        line = line.strip()

        if not line or line.startswith(("!", "[")):
            continue

        # Generic cosmetic rules start with "##"
        if line.startswith("##"):
            selector = line[2:].strip()
            if _is_valid_selector(selector):
                selectors.add(selector)

    return sorted(selectors)


def build_css(selectors: list[str]) -> str:
    """Generate a CSS stylesheet that hides all matched elements."""
    if not selectors:
        return ""

    chunk_size = 200
    chunks = []

    for i in range(0, len(selectors), chunk_size):
        chunk = selectors[i : i + chunk_size]
        selector_block = ",\n".join(chunk)
        chunks.append(
            f"{selector_block} {{\n"
            f"  display: none !important;\n"
            f"  visibility: hidden !important;\n"
            f"  height: 0 !important;\n"
            f"  overflow: hidden !important;\n"
            f"}}\n"
        )

    return "\n".join(chunks)


def build_observer_js(_selectors: list[str]) -> str:
    """Generate an incremental observer that reuses selectors from the injected CSS."""
    return """(() => {
  const SIGNATURE = '#-CookieConsentContainer';
  const OVERLAYS = '.modal-backdrop, [class*="overlay"][class*="cookie"], '
    + '[class*="overlay"][class*="consent"], [class*="overlay"][class*="gdpr"]';
  let sheet = null;
  let scheduled = false;
  let pending = [];

  const findSheet = () => {
    for (const candidate of document.styleSheets) {
      try {
        if (candidate.cssRules.length && candidate.cssRules[0].selectorText
            && candidate.cssRules[0].selectorText.includes(SIGNATURE)) {
          return candidate;
        }
      } catch (_) {}
    }
    return null;
  };

  const clean = roots => {
    sheet ||= findSheet();
    if (!sheet) return;
    for (const root of roots) {
      if (!(root instanceof Element)) continue;
      for (const rule of sheet.cssRules) {
        if (!rule.selectorText) continue;
        try {
          if (root.matches(rule.selectorText)) {
            root.remove();
            break;
          }
          root.querySelectorAll(rule.selectorText).forEach(element => element.remove());
        } catch (_) {}
      }
    }
    document.querySelectorAll(OVERLAYS).forEach(element => element.remove());
    if (document.body) document.body.style.overflow = '';
    document.documentElement.style.overflow = '';
  };

  const flush = () => {
    const roots = pending;
    pending = [];
    scheduled = false;
    clean(roots);
  };

  new MutationObserver(mutations => {
    for (const mutation of mutations) pending.push(...mutation.addedNodes);
    if (!scheduled && pending.length) {
      scheduled = true;
      setTimeout(flush, 50);
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
"""


def _is_valid_selector(selector: str) -> bool:
    if not selector:
        return False
    if len(selector) > 500:
        return False
    # Skip procedural cosmetic filters (uBlock extended syntax)
    if any(token in selector for token in [":has-text(", ":style(", ":remove(", ":matches-path("]):
        return False
    # Skip selectors with :upward, :min-text-length, etc.
    return not re.search(r":(?:upward|min-text-length|watch-attr)\(", selector)
