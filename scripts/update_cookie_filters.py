#!/usr/bin/env python3
"""Download cookie consent filter lists and generate cosmetic CSS + JS assets.

Run manually or via CI:
    python scripts/update_cookie_filters.py
"""

import sys
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.cookie_dismiss.filter_parser import build_css, build_observer_js, extract_cosmetic_selectors

FILTER_LIST_URLS = [
    "https://easylist-downloads.adblockplus.org/fanboy-annoyance.txt",
    "https://www.i-dont-care-about-cookies.eu/abp/",
]

OUTPUT_DIR = PROJECT_ROOT / "app" / "cookie_dismiss"
CSS_OUTPUT = OUTPUT_DIR / "cosmetic_filters.css"
JS_OUTPUT = OUTPUT_DIR / "observer.js"


def download_filter_list(url: str) -> str:
    print(f"  Downloading {url}")
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def main():
    all_selectors = set()

    print("Downloading filter lists...")
    for url in FILTER_LIST_URLS:
        try:
            text = download_filter_list(url)
            selectors = extract_cosmetic_selectors(text)
            print(f"  -> {len(selectors)} selectors extracted")
            all_selectors.update(selectors)
        except Exception as error:
            print(f"  -> FAILED: {error}")

    selectors = sorted(all_selectors)
    print(f"\nTotal unique selectors: {len(selectors)}")

    css = build_css(selectors)
    CSS_OUTPUT.write_text(css)
    print(f"Written CSS to {CSS_OUTPUT} ({len(css):,} bytes)")

    js = build_observer_js(selectors)
    JS_OUTPUT.write_text(js)
    print(f"Written JS to {JS_OUTPUT} ({len(js):,} bytes)")

    print("\nDone.")


if __name__ == "__main__":
    main()
