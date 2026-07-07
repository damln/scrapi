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


def build_observer_js(selectors: list[str]) -> str:
    """Generate a MutationObserver JS script that hides/removes cookie banners dynamically."""
    selectors_json = _selectors_to_json(selectors)

    return (
        "(() => {\n"
        f"  const SELECTORS = {selectors_json};\n"
        "  const hide = () => {\n"
        "    SELECTORS.forEach(sel => {\n"
        "      try {\n"
        "        document.querySelectorAll(sel).forEach(el => {\n"
        "          el.style.setProperty('display', 'none', 'important');\n"
        "        });\n"
        "      } catch(e) {}\n"
        "    });\n"
        "    document.querySelectorAll(\n"
        '      \'.modal-backdrop, [class*="overlay"][class*="cookie"], \'\n'
        '      + \'[class*="overlay"][class*="consent"], [class*="overlay"][class*="gdpr"]\'\n'
        "    ).forEach(el => el.remove());\n"
        "    document.body.style.overflow = '';\n"
        "    document.documentElement.style.overflow = '';\n"
        "  };\n"
        "  hide();\n"
        "  if (document.body) {\n"
        "    new MutationObserver(hide).observe(document.body, {childList: true, subtree: true});\n"
        "  }\n"
        "})();\n"
    )


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


def _selectors_to_json(selectors: list[str]) -> str:
    import json

    return json.dumps(selectors)
