"""X / Twitter posting recipe.

Selectors verified Jan 2026 (see docs/agents/selectors.md in the XActions
reference). The recipe runs in the action_worker subprocess against a page
that already carries the session's auth cookies, so it's logged in.

To add LinkedIn later: create app/recipes/linkedin.py with the same
fn(page, req, log) -> dict shape and register it in __init__.RECIPES.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field, field_validator, model_validator

from app.recipes import helpers

COMPOSE_BUTTON = '[data-testid="SideNav_NewTweet_Button"]'
TWEET_TEXTAREA = '[data-testid="tweetTextarea_0"]'
ANY_TEXTAREA = '[data-testid^="tweetTextarea_"]'
ADD_BUTTON = '[data-testid="addButton"]'
REPLY_BUTTON = '[data-testid="reply"]'
FILE_INPUT = "input[data-testid='fileInput']"
ATTACHMENTS = '[data-testid="attachments"]'
POST_BUTTON = '[data-testid="tweetButton"]'
POST_BUTTON_INLINE = '[data-testid="tweetButtonInline"]'
TOAST_STATUS_LINK = '[data-testid="toast"] a[href*="/status/"]'

# Clicking Post fires a POST to the CreateTweet GraphQL mutation (CreateNoteTweet
# for long-form). Its JSON response carries the new tweet's id, which is the only
# reliable way to learn the id of the post we just made.
CREATE_TWEET_RE = re.compile(r"/graphql/[^/]+/(CreateTweet|CreateNoteTweet)\b")
STATUS_ID_RE = re.compile(r"/status/(\d+)")

MAX_X_POST_LEN = 25_000


class XPostParams(BaseModel):
    text: str | None = Field(
        None,
        max_length=MAX_X_POST_LEN,
        description="First tweet body, or reply body when reply_url is set.",
    )
    thread: list[str] = Field(
        default_factory=list,
        description=f"Additional tweet bodies. Each item must be {MAX_X_POST_LEN} chars or less.",
    )
    reply_url: str | None = Field(
        None,
        description="Absolute X/Twitter status URL to reply to. Omit to create a new post/thread.",
    )
    dry_run: bool = Field(True, description="When true, compose but do not publish.")

    model_config = {"extra": "forbid"}

    @field_validator("thread")
    @classmethod
    def validate_thread(cls, values: list[str]) -> list[str]:
        over = [index for index, value in enumerate(values) if len(value) > MAX_X_POST_LEN]
        if over:
            raise ValueError(f"thread item(s) exceed {MAX_X_POST_LEN} chars at index {over}")
        return values

    @field_validator("reply_url")
    @classmethod
    def validate_reply_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("reply_url must be an absolute http or https URL")
        return value

    @model_validator(mode="after")
    def validate_text_source(self) -> XPostParams:
        if self.text is None and not self.thread:
            raise ValueError("x_post requires text or a non-empty thread")
        return self


def _composer_open(page, timeout: int = 4000) -> bool:
    """True if the compose textarea is already on screen (e.g. /compose/post)."""
    try:
        page.locator(TWEET_TEXTAREA).first.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        return False
    return True


def _dismiss_composer_suggestions(page, editor, timeout: int, log: list[str]) -> None:
    controls = editor.get_attribute("aria-controls")
    if not controls:
        return
    suggestions = page.locator(f'[id={json.dumps(controls)}][role="listbox"]')
    if not suggestions.is_visible():
        return
    # X opens hashtag suggestions even for URL fragments. Its backdrop blocks Post.
    page.keyboard.press("Escape")
    suggestions.wait_for(state="hidden", timeout=timeout)
    log.append("dismissed composer suggestions")


def _rest_id_from_payload(payload: Any) -> str | None:
    """Pull the new tweet's id out of a CreateTweet GraphQL response body.

    Standard tweets nest it under ``data.create_tweet`` and long-form notes
    under ``data.notetweet_create``; both expose ``tweet_results.result.rest_id``
    (with ``legacy.id_str`` as a backup). Returns None if the shape doesn't match.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("create_tweet", "notetweet_create"):
        node = data.get(key)
        if not isinstance(node, dict):
            continue
        result = node.get("tweet_results")
        result = result.get("result") if isinstance(result, dict) else None
        if not isinstance(result, dict):
            continue
        rest_id = result.get("rest_id")
        if rest_id:
            return str(rest_id)
        legacy = result.get("legacy")
        if isinstance(legacy, dict) and legacy.get("id_str"):
            return str(legacy["id_str"])
    return None


def _tweet_id_from_toast(page, timeout: int) -> str | None:
    """Fallback: read the id from the 'View' link in the success toast.

    The toast is ephemeral (~5s), so this is only a backstop for when the
    CreateTweet response body couldn't be parsed.
    """
    try:
        href = page.locator(TOAST_STATUS_LINK).first.get_attribute("href", timeout=min(timeout, 5000))
    except PlaywrightTimeoutError:
        return None
    if not href:
        return None
    match = STATUS_ID_RE.search(href)
    return match.group(1) if match else None


def _confirm_posted_via_modal(page, composer_handle, timeout: int, log: list[str]) -> bool:
    """Success = the compose modal closes, i.e. THIS textarea element goes away
    ("hidden" covers both detached and not-visible). Falls back to a
    selector-detach wait if we never captured a handle."""
    try:
        if composer_handle is not None:
            composer_handle.wait_for_element_state("hidden", timeout=timeout)
        else:
            page.locator(TWEET_TEXTAREA).first.wait_for(state="detached", timeout=timeout)
    except PlaywrightTimeoutError:
        log.append("composer did not close; post may have failed")
        return False
    return True


def x_post(page, req: dict[str, Any], log: list[str]) -> dict[str, Any]:
    """Post a single tweet, a thread, or a reply — with optional media.

    params: {text?, thread?: [str], reply_url?, dry_run?=True}
    """
    params = XPostParams.model_validate(req.get("params") or {})
    text = params.text
    thread = params.thread
    reply_url = params.reply_url
    dry_run = params.dry_run
    timeout = req["timeout_ms"]

    tweets = [text, *thread] if text is not None else list(thread)
    tweets = [t for t in tweets if t is not None]
    if not tweets:
        raise ValueError("x_post requires 'text' or a non-empty 'thread'")
    over = [i for i, t in enumerate(tweets) if len(t) > MAX_X_POST_LEN]
    if over:
        raise ValueError(f"tweet(s) exceed {MAX_X_POST_LEN} chars at index {over}")

    # Open the composer. Reply mode targets an existing status URL.
    if reply_url:
        page.goto(reply_url, wait_until="domcontentloaded", timeout=timeout)
        if not helpers.click_first(page, [REPLY_BUTTON], timeout):
            raise ValueError("reply button not found on the target status")
    elif not _composer_open(page):
        # On /compose/post the modal is already open; only click the sidebar
        # button when it isn't (e.g. landing on /home). Clicking it while the
        # modal is open fails Playwright's pointer check — the button sits
        # behind the dialog overlay.
        if not helpers.click_first(page, [COMPOSE_BUTTON], timeout):
            raise ValueError("could not open the composer")

    first = page.locator(TWEET_TEXTAREA).first
    first.wait_for(state="visible", timeout=timeout)
    # Hold a handle to THIS composer element so we can detect the modal
    # closing after posting. Re-querying the selector is unreliable because
    # /home (where a successful post lands) has its own inline tweetTextarea_0.
    composer_handle = first.element_handle()

    helpers.upload_media(page, req.get("media_paths") or [], FILE_INPUT, ATTACHMENTS, timeout, log)

    helpers.type_into(page, first, tweets[0])
    _dismiss_composer_suggestions(page, first, timeout, log)
    log.append(f"typed tweet 1/{len(tweets)}")

    for index, body in enumerate(tweets[1:], start=2):
        page.locator(ADD_BUTTON).first.click()
        page.wait_for_timeout(600)
        editor = page.locator(ANY_TEXTAREA).last
        helpers.type_into(page, editor, body)
        _dismiss_composer_suggestions(page, editor, timeout, log)
        log.append(f"typed tweet {index}/{len(tweets)}")

    if dry_run:
        log.append("dry_run: not publishing")
        return {"posted": False, "dry_run": True, "tweets": len(tweets)}

    # Click Post while watching for the CreateTweet GraphQL response, which both
    # confirms the post landed and carries its id. For a thread the first match
    # is the root tweet — exactly the permalink we want.
    tweet_id: str | None = None
    posted = True
    try:
        with page.expect_response(
            lambda r: bool(CREATE_TWEET_RE.search(r.url)) and r.request.method == "POST",
            timeout=timeout,
        ) as resp_info:
            if not helpers.click_first(page, [POST_BUTTON, POST_BUTTON_INLINE], timeout):
                raise ValueError("post button not found")
        response = resp_info.value
        posted = response.ok
        if not posted:
            log.append(f"CreateTweet returned HTTP {response.status}")
        else:
            try:
                tweet_id = _rest_id_from_payload(response.json())
            except Exception:  # body may not be valid JSON
                tweet_id = None
            log.append(f"captured tweet id {tweet_id}" if tweet_id else "tweet id not in response")
    except PlaywrightTimeoutError:
        # No CreateTweet response observed — fall back to the modal-close heuristic.
        log.append("no CreateTweet response; falling back to modal-close detection")
        posted = _confirm_posted_via_modal(page, composer_handle, timeout, log)

    # Backstop: if we posted but never parsed an id, read it off the success toast.
    if posted and not tweet_id:
        tweet_id = _tweet_id_from_toast(page, timeout)
        if tweet_id:
            log.append(f"captured tweet id {tweet_id} from toast")

    result: dict[str, Any] = {"posted": posted, "dry_run": False, "tweets": len(tweets)}
    if tweet_id:
        result["tweet_id"] = tweet_id
        # /i/status/<id> resolves without needing the author's handle.
        result["permalink"] = f"https://x.com/i/status/{tweet_id}"
    return result
