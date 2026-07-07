"""Platform-agnostic Playwright DOM helpers shared by action recipes.

Nothing here knows about X or LinkedIn — selectors are always passed in by
the platform recipe (``app/recipes/twitter.py`` etc.). Runs inside the
``action_worker`` subprocess (Playwright sync API).
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Generic file input, used by the raw-script escape hatch where the platform
# isn't known. Recipes pass their own (e.g. X's data-testid="fileInput").
ANY_FILE_INPUT = 'input[type="file"]'


def click_first(page, selectors: list[str], timeout: int) -> bool:
    """Click the first selector that becomes visible. Returns False if none do."""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError:
            continue
        locator.click()
        return True
    return False


def type_into(page, locator, text: str) -> None:
    """Insert text into a React contenteditable via real keyboard events."""
    locator.click()
    page.keyboard.insert_text(text)


def upload_media(
    page,
    media_paths: list[str],
    file_input_selector: str,
    preview_selector: str | None,
    timeout: int,
    log: list[str],
) -> None:
    """Attach files through a real file input (works on hidden inputs).

    ``preview_selector`` (when given) is waited on so a post isn't published
    mid-upload; pass None to skip the wait.
    """
    if not media_paths:
        return
    file_input = page.locator(file_input_selector).first
    file_input.wait_for(state="attached", timeout=timeout)
    file_input.set_input_files(media_paths)
    log.append(f"uploaded {len(media_paths)} media file(s)")
    if preview_selector:
        try:
            page.locator(preview_selector).first.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError:
            log.append("media preview not detected; continuing")
    page.wait_for_timeout(1500)


# Recipe signature, for reference: fn(page, req: dict, log: list[str]) -> dict[str, Any]
Recipe = Any
