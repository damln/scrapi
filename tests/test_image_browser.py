import asyncio
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from cloakbrowser import launch_async

from app import chatgpt_browser
from app.chatgpt_browser import ChatGPTBrowser, GenerationError, load_session


@pytest.mark.skipif(os.environ.get("SCRAPI_BROWSER_TESTS") != "1", reason="Opt-in real CloakBrowser integration tests")
class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser = await launch_async(headless=True)
        self.page = await self.browser.new_page()
        self.adapter = ChatGPTBrowser()

    async def set_content(self, html):
        await self.page.goto("data:text/html," + quote(html), wait_until="domcontentloaded")

    async def asyncTearDown(self):
        await self.browser.close()

    async def test_retrieves_only_assistant_images(self):
        await self.set_content("""
            <article data-testid="conversation-turn-0">
                <div data-message-author-role="user"><img id="reference"></div>
            </article>
            <section data-testid="conversation-turn-1" data-turn="assistant">
                <div>Generated<img id="output"></div>
                <button aria-label="Copy response">Copy</button>
            </section>
        """)
        await self.page.evaluate("""() => {
            const canvas = document.createElement('canvas')
            canvas.width = 512
            canvas.height = 512
            const ctx = canvas.getContext('2d')
            ctx.fillStyle = 'red'
            ctx.fillRect(0, 0, 512, 512)
            document.querySelector('#output').src = canvas.toDataURL('image/png')
            ctx.fillStyle = 'blue'
            ctx.fillRect(0, 0, 512, 512)
            document.querySelector('#reference').src = canvas.toDataURL('image/png')
        }""")
        async with asyncio.timeout(20):
            result = await self.adapter.wait_for_result(self.page)
        assert len(result["images"]) == 1
        assert base64.b64decode(result["images"][0]["b64_json"]).startswith(b"\x89PNG")

    async def test_text_only_reply(self):
        await self.set_content("""
            <article data-testid="conversation-turn-1">
                <div data-message-author-role="assistant">Please describe the image.</div>
                <button aria-label="Copy">Copy</button>
            </article>
        """)
        async with asyncio.timeout(20):
            result = await self.adapter.wait_for_result(self.page)
        assert result["images"] == []
        assert "Please describe" in result["text"]

    async def test_existing_reply_is_ignored_until_new_reply_arrives(self):
        await self.set_content("""
            <article data-testid="conversation-turn-1" data-turn="assistant">
                Old reply<button aria-label="Copy">Copy</button>
            </article>
        """)
        task = asyncio.create_task(self.adapter.wait_for_result(self.page, previous_turns=["conversation-turn-1"]))
        try:
            await asyncio.sleep(9)
            assert not task.done(), "An old reply must not complete a new job"
            await self.page.evaluate("""() => {
                document.body.insertAdjacentHTML('beforeend', `
                    <article data-testid="conversation-turn-3" data-turn="assistant">
                        New reply<button aria-label="Copy">Copy</button>
                    </article>`)
            }""")
            async with asyncio.timeout(15):
                result = await task
            assert "New reply" in result["text"]
            assert "Old reply" not in result["text"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_generate_navigates_to_requested_conversation(self):
        url = "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
        context = await self.browser.new_context()
        visited = []

        async def respond(route):
            visited.append(route.request.url)
            await route.fulfill(
                content_type="text/html",
                body="""
                <article data-testid="conversation-turn-1" data-turn="assistant">
                    Original image<button aria-label="Copy">Copy</button>
                </article>
                <div id="prompt-textarea" contenteditable="true"></div>
                <button data-testid="send-button" onclick="
                    const reply = document.createElement('article')
                    reply.dataset.testid = 'conversation-turn-3'
                    reply.dataset.turn = 'assistant'
                    reply.textContent = document.querySelector('#prompt-textarea').innerText
                    reply.insertAdjacentHTML('beforeend', '<button aria-label=Copy>Copy</button>')
                    document.body.append(reply)
                ">Send</button>
                """,
            )

        await context.route("**/*", respond)
        with (
            patch.object(chatgpt_browser, "launch_async", AsyncMock(return_value=self.browser)),
            patch.object(self.browser, "new_context", AsyncMock(return_value=context)),
        ):
            async with asyncio.timeout(20):
                result = await self.adapter.generate("Make it blue", [], {}, "", url)
        assert visited[0] == url
        assert result["conversation_url"] == url
        assert "Make it blue" in result["text"]
        assert "Original image" not in result["text"]

    async def test_conversation_redirect_is_rejected(self):
        await self.set_content('<article data-testid="conversation-turn-1">Unrelated chat</article>')
        with pytest.raises(GenerationError, match="conversation_unavailable"):
            await self.adapter.check_conversation(
                self.page, "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
            )

    async def test_missing_conversation_is_rejected(self):
        await self.set_content('<div id="prompt-textarea" contenteditable="true"></div>')
        self.page.set_default_timeout(100)
        with pytest.raises(GenerationError, match="conversation_unavailable"):
            await self.adapter.check_conversation(
                self.page, "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
            )

    async def test_chatgpt_response_error_fails_without_waiting_for_an_image(self):
        await self.set_content("""
            <article data-testid="conversation-turn-1">
                <div data-message-author-role="assistant">
                    Something went wrong while generating the response.
                </div>
                <button>Retry</button>
            </article>
        """)
        with pytest.raises(GenerationError, match="chatgpt_response_error"):
            async with asyncio.timeout(2):
                await self.adapter.wait_for_result(self.page)

    async def test_login_and_verification_errors(self):
        for html, error in (
            ('<button data-testid="login-button">Log in</button>', "session_expired"),
            ("<h1>Verify you are human</h1>", "browser_verification_required"),
        ):
            await self.set_content(html)
            with pytest.raises(GenerationError, match=error):
                await self.adapter.check_access(self.page)

    async def test_conversation_text_is_not_a_browser_challenge(self):
        await self.set_content('<p>Draw a sign saying "verify you are human".</p>')
        await self.adapter.check_access(self.page)

    async def test_prompt_recovers_when_editor_discards_early_input(self):
        await self.set_content("""
            <div id="prompt-textarea" contenteditable="true"></div>
            <script>
            const editor = document.querySelector('#prompt-textarea')
            editor.addEventListener('input', () => {
                editor.innerHTML = ''
            }, {once: true})
            </script>
        """)
        editor = self.page.locator("#prompt-textarea")
        await self.adapter.enter_prompt(editor, "Draw a fox.\nUse watercolor.")
        text = await editor.inner_text()
        assert "Draw a fox." in text
        assert "Use watercolor." in text
        assert text.count("Draw a fox.") == 1

    async def test_backend_challenge_and_authentication_failures(self):
        for status, headers, code in (
            (403, {"cf-mitigated": "challenge"}, "browser_verification_required"),
            (401, {}, "session_expired"),
            (403, {}, "chatgpt_access_denied"),
            (429, {}, "chatgpt_rate_limited"),
        ):
            errors = set()
            response = SimpleNamespace(
                url="https://chatgpt.com/backend-api/f/conversation",
                status=status,
                headers=headers,
            )
            self.adapter.record_response_error(response, errors)
            with pytest.raises(GenerationError, match=code):
                async with asyncio.timeout(2):
                    await self.adapter.wait_for_result(self.page, errors)

    async def test_unrelated_403_is_not_a_generation_failure(self):
        errors = set()
        self.adapter.record_response_error(
            SimpleNamespace(
                url="https://chatgpt.com/backend-api/telemetry",
                status=403,
                headers={},
            ),
            errors,
        )
        assert errors == set()

    async def test_session_profile_applies_to_chromium(self):
        payload = {
            "id": "example",
            "label": "Example",
            "domains": ["chatgpt.com"],
            "user_agent": "SessionProfileTest/1.0",
            "viewport": {"height": 900, "width": 1200},
            "locale": "en-US",
            "timezone": "Europe/Madrid",
            "extra_headers": {"X-Profile-Test": "example"},
            "cookies": [
                {
                    "name": "__Secure-next-auth.session-token.0",
                    "value": "dummy%2Fchunk",
                    "domain": ".chatgpt.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
                {
                    "name": "__Secure-next-auth.session-token.1",
                    "value": '"dummy=chunk"',
                    "domain": ".chatgpt.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
                {"name": "subdomain", "value": "dummy", "domain": "ws.chatgpt.com"},
                {"name": "unrelated", "value": "dummy", "domain": "other.example"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text(json.dumps(payload))
            options = load_session(path)
        context = await self.browser.new_context(**options)
        try:
            requests = []

            async def respond(route):
                requests.append(route.request.headers)
                await route.fulfill(content_type="text/html", body="<p>Profile test</p>")

            await context.route("**/*", respond)
            page = await context.new_page()
            await page.goto("https://chatgpt.com/")
            actual = await page.evaluate("""() => ({
                user_agent: navigator.userAgent, locale: navigator.language,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                viewport: {width: innerWidth, height: innerHeight}
            })""")
            for field in ("user_agent", "locale", "timezone", "viewport"):
                assert actual[field] == payload[field]
            assert requests[0]["x-profile-test"] == "example"
            cookies = {cookie["name"]: cookie for cookie in await context.cookies()}
            assert "unrelated" not in cookies
            assert "subdomain" in cookies
            for source in payload["cookies"][:2]:
                assert cookies[source["name"]]["value"] == source["value"]
                assert cookies[source["name"]]["httpOnly"]
                assert cookies[source["name"]]["expires"] == -1
        finally:
            await context.close()
