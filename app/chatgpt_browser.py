"""ChatGPT UI adapter, adapted from damln/chatgpt-images-api. Uses Scrapi CloakBrowser."""

import asyncio
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cloakbrowser import launch_async
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError


class GenerationError(Exception):
    pass


# ChatGPT ships two DOMs: the older one keys turns with data-testid, the newer
# app shell keys them with data-content-search-turn-key and has no test ids.
TURNS = '[data-testid^="conversation-turn-"], [data-content-search-turn-key]'
ASSISTANT_TURNS = (
    '[data-testid^="conversation-turn-"][data-turn="assistant"], '
    '[data-testid^="conversation-turn-"]:has([data-message-author-role="assistant"]), '
    '[data-content-search-turn-key]:has([data-chatgpt-search-unit-key$=":assistant"]), '
    '[data-content-search-turn-key]:has([data-testid="generated-image-gallery"])'
)
TURN_KEY = "e => e.getAttribute('data-testid') || e.getAttribute('data-content-search-turn-key')"
SEND_BUTTON = '[data-testid="send-button"], form:has([role="textbox"]) button[type="submit"]'
STOP_BUTTON = '[data-testid="stop-button"], button[aria-label="Stop"]'
# Text and images of the assistant part of a turn. The newer DOM wraps the
# user's message, including attached reference images, in the same turn, and
# an image-only reply has no assistant unit, only a generated image gallery.
READ_TURN = """turn => {
    const user = '[data-message-author-role="user"], [data-chatgpt-search-unit-key$=":user"], [data-user-message-bubble]'
    const parts = turn.querySelectorAll('[data-message-author-role="assistant"], [data-chatgpt-search-unit-key$=":assistant"]')
    const sources = [...turn.querySelectorAll('img')].filter(e => !e.closest(user) && e.complete &&
        e.naturalWidth >= 256 && e.naturalHeight >= 256).map(e => e.currentSrc || e.src)
    let text = [...parts].map(part => part.innerText).join('\\n')
    if (!parts.length) {
        const reply = turn.cloneNode(true)
        reply.querySelectorAll(user).forEach(e => e.remove())
        text = reply.textContent.trim()
    }
    return {text, sources, complete: !!turn.querySelector('[data-talvt-turn-state="complete"]')}
}"""


def load_session(path: Path) -> dict:
    try:
        return normalize_session(json.loads(path.read_text()))
    except (OSError, ValueError):
        raise GenerationError("session_missing_or_invalid") from None


def normalize_session(value) -> dict:
    try:
        if isinstance(value, list):
            value = {"cookies": value}
        cookies = value["cookies"]
        if not isinstance(cookies, list) or not cookies:
            raise GenerationError("session_missing_or_invalid")
        normalized = []
        for cookie in cookies:
            domain = cookie.get("domain", "").lstrip(".")
            if domain != "chatgpt.com" and not domain.endswith(".chatgpt.com"):
                continue
            normalized.append(
                {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie["domain"],
                    "path": cookie.get("path", "/"),
                    "expires": cookie.get("expires", cookie.get("expirationDate", -1)),
                    "httpOnly": cookie.get("httpOnly", False),
                    "secure": cookie.get("secure", True),
                    "sameSite": {
                        "strict": "Strict",
                        "lax": "Lax",
                        "none": "None",
                        "no_restriction": "None",
                    }.get(str(cookie.get("sameSite", "Lax")).lower(), "Lax"),
                }
            )
        if not normalized:
            raise GenerationError("session_missing_or_invalid")
        origins = [o for o in value.get("origins", []) if o.get("origin") == "https://chatgpt.com"]
        return {
            "storage_state": {"cookies": normalized, "origins": origins},
            **context_options(value),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise GenerationError("session_missing_or_invalid") from None


def context_options(value: dict) -> dict:
    options: dict = {"locale": "en-US"}
    for source, target in (
        ("user_agent", "user_agent"),
        ("locale", "locale"),
        ("timezone", "timezone_id"),
    ):
        if source in value:
            setting = value[source]
            if not isinstance(setting, str) or not setting.strip():
                raise ValueError()
            options[target] = setting
    if "timezone_id" in options:
        ZoneInfo(options["timezone_id"])
    if "viewport" in value:
        viewport = value["viewport"]
        if not isinstance(viewport, dict) or any(
            type(viewport.get(key)) is not int or viewport[key] <= 0 for key in ("width", "height")
        ):
            raise ValueError()
        options["viewport"] = {key: viewport[key] for key in ("width", "height")}
    if "extra_headers" in value:
        headers = value["extra_headers"]
        if not isinstance(headers, dict) or any(
            not isinstance(name, str)
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
            or not isinstance(content, str)
            or "\r" in content
            or "\n" in content
            for name, content in headers.items()
        ):
            raise ValueError()
        options["extra_http_headers"] = headers
    return options


class ChatGPTBrowser:
    async def generate(
        self, prompt: str, images: list[dict], session: dict, proxy_url: str, conversation_url: str | None = None
    ) -> dict:
        browser = None
        stage = "browser_start"
        try:
            browser = await launch_async(headless=True, proxy=proxy_url or None)
            stage = "session_restore"
            context = await browser.new_context(
                **session,
                accept_downloads=True,
            )
            page = await context.new_page()
            response_errors: set[str] = set()
            page.on(
                "response",
                lambda response: self.record_response_error(response, response_errors),
            )
            page.set_default_timeout(30000)
            stage = "navigation"
            await page.goto(conversation_url or "https://chatgpt.com/", wait_until="domcontentloaded")
            await self.check_access(page)
            stage = "composer"
            # ChatGPT replaced #prompt-textarea with an unnamed ProseMirror textbox.
            editor = page.locator('#prompt-textarea, [contenteditable="true"][role="textbox"]').first
            # The proxied app shell can take well over 30 seconds to hydrate.
            await editor.wait_for(state="visible", timeout=90000)
            await self.check_access(page)
            self.check_response_errors(response_errors)
            if conversation_url:
                stage = "conversation_load"
                await self.check_conversation(page, conversation_url)
            if images:
                stage = "image_upload"
                await self.attach_images(page, images)
            stage = "prompt_entry"
            await self.enter_prompt(editor, prompt)
            if conversation_url:
                await self.check_conversation(page, conversation_url)
            previous_turns = await page.locator(TURNS).evaluate_all(f"elements => elements.map({TURN_KEY})")
            stage = "submission"
            send = page.locator(SEND_BUTTON).first
            # The send button is disabled while attachments are uploading.
            await send.click()
            stage = "result"
            return await self.wait_for_result(page, response_errors, previous_turns)
        except PlaywrightTimeoutError:
            raise GenerationError(f"{stage}_timeout") from None
        except PlaywrightError:
            raise GenerationError(f"{stage}_failed") from None
        finally:
            if browser is not None:
                await browser.close()

    async def attach_images(self, page, images, preview_timeout=8000):
        # Files set before the app hydrates are silently dropped, so set them
        # again until the composer shows a preview for each one.
        for attempt in range(6):
            upload = page.locator('input[type="file"]').first
            if not await upload.count():
                await page.get_by_role("button", name=re.compile("Add photos|Attach|Add files", re.I)).first.click()
            if attempt:
                # Setting the same files twice fires no change event.
                await upload.set_input_files([])
            await upload.set_input_files(images)
            try:
                await self.wait_for_uploads(upload, len(images), settled=False, limit_ms=preview_timeout)
                break
            except PlaywrightTimeoutError:
                continue
        else:
            raise GenerationError("image_upload_failed")
        # The app shell keeps the send button enabled while attachments upload.
        await self.wait_for_uploads(upload, len(images), settled=True, limit_ms=120000)

    async def wait_for_uploads(self, upload, count, settled, limit_ms):
        await upload.page.wait_for_function(
            """([input, count, settled]) => {
                const form = input.closest('form')
                if (!form) return true
                return form.querySelectorAll('img').length >= count &&
                    !(settled && form.querySelector('[aria-busy="true"], [role="progressbar"]'))
            }""",
            arg=[await upload.element_handle(), count, settled],
            timeout=limit_ms,
        )

    async def check_conversation(self, page, conversation_url):
        try:
            await page.locator(TURNS).first.wait_for(state="visible")
        except PlaywrightTimeoutError:
            raise GenerationError("conversation_unavailable") from None
        current = urlsplit(page.url)
        if (
            current.hostname != "chatgpt.com"
            or current.path.rstrip("/").split("/")[-1] != conversation_url.rsplit("/", 1)[-1]
        ):
            raise GenerationError("conversation_unavailable")

    async def enter_prompt(self, editor, prompt):
        text = "Generate an image using your image generation tool.\n" + prompt
        for _ in range(10):
            await editor.fill(text)
            await asyncio.sleep(0.5)
            if " ".join((await editor.inner_text()).split()) == " ".join(text.split()):
                return
        raise GenerationError("prompt_not_retained")

    async def check_access(self, page):
        text = (await page.title()).lower()
        text += " " + " ".join(await page.locator("h1, h2").all_inner_texts()).lower()
        if any(x in text for x in ("verify you are human", "checking your browser", "just a moment")):
            raise GenerationError("browser_verification_required")
        if await page.locator('[data-testid="login-button"]').is_visible():
            raise GenerationError("session_expired")
        if "/auth/" in page.url or "auth.openai.com" in page.url:
            raise GenerationError("session_expired")

    def record_response_error(self, response, errors):
        url = urlsplit(response.url)
        if url.hostname != "chatgpt.com" or not url.path.startswith("/backend-api/"):
            return
        if response.headers.get("cf-mitigated") == "challenge":
            errors.add("browser_verification_required")
        elif url.path in {
            "/backend-api/f/conversation",
            "/backend-api/conversation",
            "/backend-api/f/conversation/prepare",
        }:
            code = {
                401: "session_expired",
                403: "chatgpt_access_denied",
                429: "chatgpt_rate_limited",
            }.get(response.status)
            if code:
                errors.add(code)

    def check_response_errors(self, errors):
        for code in (
            "browser_verification_required",
            "session_expired",
            "chatgpt_access_denied",
            "chatgpt_rate_limited",
        ):
            if code in errors:
                raise GenerationError(code)

    async def wait_for_result(self, page, response_errors=None, previous_turns=()) -> dict:
        assistants = page.locator(ASSISTANT_TURNS)
        if previous_turns:
            exclusions = "".join(
                f":not([data-testid={json.dumps(turn)}]):not([data-content-search-turn-key={json.dumps(turn)}])"
                for turn in previous_turns
            )
            assistants = assistants.and_(page.locator(exclusions))
        assistant = assistants.last
        stop = page.locator(STOP_BUTTON).first
        previous = None
        stable_since = asyncio.get_running_loop().time()
        while True:
            self.check_response_errors(response_errors or set())
            await self.check_access(page)
            if await assistant.count():
                turn = await assistant.evaluate(READ_TURN)
                text, sources = turn["text"], turn["sources"]
                if "something went wrong while generating the response" in text.lower():
                    raise GenerationError("chatgpt_response_error")
                signature = (text, tuple(sources))
                if signature != previous or await stop.is_visible():
                    previous = signature
                    stable_since = asyncio.get_running_loop().time()
                finished = (
                    turn["complete"]
                    or await assistant.get_by_role(
                        "button", name=re.compile("Copy|Good response|Bad response", re.I)
                    ).count()
                )
                if finished and asyncio.get_running_loop().time() - stable_since >= 8:
                    results = []
                    if len(set(sources)) > 4:
                        raise GenerationError("too_many_output_images")
                    for src in dict.fromkeys(sources):
                        results.append(await self.read_image(page, src))
                    return {"images": results, "text": text, "conversation_url": page.url}
            await asyncio.sleep(1)

    async def read_image(self, page, src):
        result = await page.evaluate(
            """async ({src, limit}) => {
            const response = await fetch(src, {credentials: 'include'})
            if (!response.ok) throw new Error('image_download_failed')
            const reader = response.body.getReader()
            const chunks = []
            let size = 0
            while (true) {
                const {value, done} = await reader.read()
                if (done) break
                size += value.length
                if (size > limit) {
                    await reader.cancel()
                    throw new Error('image_too_large')
                }
                chunks.push(value)
            }
            const blob = new Blob(chunks, {type: response.headers.get('content-type') || ''})
            return await new Promise((resolve, reject) => {
                const file = new FileReader()
                file.onload = () => resolve(file.result)
                file.onerror = reject
                file.readAsDataURL(blob)
            })
        }""",
            {"src": src, "limit": 20 * 1024 * 1024},
        )
        header, encoded = result.split(",", 1)
        mime = header.removeprefix("data:").split(";")[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise GenerationError("unexpected_image_type")
        if not base64.b64decode(encoded):
            raise GenerationError("empty_image")
        return {"mime_type": mime, "b64_json": encoded}
