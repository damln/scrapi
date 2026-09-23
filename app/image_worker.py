"""One isolated browser per image job. Input and output never go to logs."""

import asyncio
import base64
import json
import sys

from app.chatgpt_browser import ChatGPTBrowser, GenerationError


async def run(payload: dict) -> dict:
    images = [
        {
            "name": f"reference-{index}.{image['mime_type'].split('/')[1]}",
            "mimeType": image["mime_type"],
            "buffer": base64.b64decode(image["b64_json"], validate=True),
        }
        for index, image in enumerate(payload["images"])
    ]
    return await ChatGPTBrowser().generate(
        payload["prompt"], images, payload["session"], payload["proxy_url"], payload.get("conversation_url")
    )


def main() -> None:
    try:
        result = asyncio.run(run(json.loads(sys.stdin.buffer.read())))
        response: dict = {"result": result}
    except GenerationError as exc:
        response = {"error": str(exc)}
    except Exception:
        response = {"error": "browser_error"}
    sys.stdout.write(json.dumps(response))


if __name__ == "__main__":
    main()
