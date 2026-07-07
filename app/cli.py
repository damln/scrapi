"""Command-line interface — the full scraping pipeline without HTTP.

Runs the same code paths as the API endpoints (provider fallback chain,
content validation, markdown conversion, PDF/PNG export, browser
actions) directly in-process. No server, no SCRAPI_API_TOKEN needed.

Usage (from the repo, a venv, or inside the Docker image):

    python -m app.cli content https://example.com
    python -m app.cli content https://example.com --format markdown
    python -m app.cli asset https://example.com/logo.png -o logo.png
    python -m app.cli export --url https://example.com -o page.pdf
    python -m app.cli actions --request request.json
    python -m app.cli status
    python -m app.cli agent

Docker one-shot (same image as the server):

    docker run --rm scrapi python -m app.cli content https://example.com
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app import asset_fetcher, firecrawl_fetcher, twitter_fetcher, youtube_fetcher
from app.action_runner import ActionError, ActionRequest, run_action
from app.fetcher import DEFAULT_PROVIDER_ORDER, fetch_urls
from app.pdf_renderer import PdfRenderError, PdfRenderRequest, render_export
from app.proxy_profiles import ProxyProfileError, resolve_proxy_profile
from app.status import get_status


@asynccontextmanager
async def _http_clients() -> AsyncIterator[None]:
    """Mirror app.main's lifespan: shared httpx clients for the fetchers."""
    asset_fetcher.init_client()
    firecrawl_fetcher.init_client()
    twitter_fetcher.init_client()
    youtube_fetcher.init_client()
    try:
        yield
    finally:
        await asset_fetcher.close_client()
        await firecrawl_fetcher.close_client()
        await twitter_fetcher.close_client()
        await youtube_fetcher.close_client()


def _emit_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return 1


def _write_bytes(data: bytes, output: str | None) -> None:
    if output and output != "-":
        Path(output).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)


async def _cmd_content(args: argparse.Namespace) -> int:
    providers = [p.strip() for p in args.provider_order.split(",") if p.strip()]
    invalid = [p for p in providers if p not in set(DEFAULT_PROVIDER_ORDER)]
    if invalid:
        return _fail(f"invalid providers: {', '.join(invalid)}. Valid: {', '.join(DEFAULT_PROVIDER_ORDER)}")

    try:
        resolve_proxy_profile(args.proxy_profile)
    except ProxyProfileError as exc:
        return _fail(str(exc))

    if args.format != "json" and len(args.urls) > 1:
        return _fail(f"--format {args.format} requires a single URL")

    async with _http_clients():
        results = await fetch_urls(
            args.urls,
            no_style=args.no_style,
            no_script=args.no_script,
            provider_order=providers,
            scroll_full=args.scroll_full,
            wait_until=args.wait_until,
            wait_for_selector=args.wait_for_selector,
            proxy_profile=args.proxy_profile,
        )

    if args.format == "json":
        _emit_json({"results": results})
        return 0 if all(r.get("status") == "success" for r in results) else 1

    result = results[0]
    if result.get("status") != "success":
        return _fail(result.get("error") or "fetch failed")
    body = result.get(args.format)
    if not body:
        return _fail(f"no {args.format} in result")
    sys.stdout.write(body + "\n")
    return 0


async def _cmd_asset(args: argparse.Namespace) -> int:
    async with _http_clients():
        result = await asset_fetcher.fetch_and_process_asset(
            args.url, args.output_format, args.max_width, args.max_height
        )

    if result.get("status") != "success":
        return _fail(result.get("error") or "asset fetch failed")

    if args.output:
        _write_bytes(base64.b64decode(result["data"]), args.output)
        meta = {k: v for k, v in result.items() if k != "data"}
        sys.stderr.write(json.dumps(meta, ensure_ascii=False) + "\n")
    else:
        _emit_json(result)
    return 0


async def _cmd_export(args: argparse.Namespace) -> int:
    if args.request:
        body = json.loads(Path(args.request).read_text())
    else:
        if bool(args.url) == bool(args.html_file):
            return _fail("exactly one of --url or --html-file is required (or use --request)")
        body = {"type": args.type}
        if args.url:
            body["url"] = args.url
        else:
            body["html"] = Path(args.html_file).read_text()

    try:
        request = PdfRenderRequest.model_validate(body)
    except ValidationError as exc:
        return _fail(str(exc))

    try:
        result = await render_export(request)
    except PdfRenderError as exc:
        return _fail(str(exc))

    _write_bytes(result.data, args.output)
    return 0


async def _cmd_actions(args: argparse.Namespace) -> int:
    raw = sys.stdin.read() if args.request == "-" else Path(args.request).read_text()
    try:
        request = ActionRequest.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        return _fail(str(exc))

    try:
        result = await run_action(request)
    except ActionError as exc:
        return _fail(str(exc))

    _emit_json(
        {
            "status": result.status,
            "result": result.result,
            "log": result.log,
            "final_url": result.final_url,
            "screenshot_base64": result.screenshot_base64,
        }
    )
    return 0 if result.status == "success" else 1


async def _cmd_status(args: argparse.Namespace) -> int:
    result = await get_status(args.proxy_profile)
    _emit_json(result)
    return 0 if result.get("status") == "ok" else 1


async def _cmd_agent(_args: argparse.Namespace) -> int:
    # Imported lazily: pulls in app.main (FastAPI route table) only for
    # this command, keeping plain fetches free of the server module.
    from app.agent_docs import render_agent_markdown
    from app.main import app

    sys.stdout.write(render_agent_markdown(app))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrapi", description="Scrapi CLI — scrape without the HTTP server")
    sub = parser.add_subparsers(dest="command", required=True)

    content = sub.add_parser("content", help="Fetch pages through the provider fallback chain")
    content.add_argument("urls", nargs="+", help="URLs to fetch")
    content.add_argument("--no-style", action="store_true", help="Remove inline style attributes")
    content.add_argument("--no-script", action="store_true", help="Remove inline script tags")
    content.add_argument("--provider-order", default=",".join(DEFAULT_PROVIDER_ORDER))
    content.add_argument("--scroll-full", action="store_true", help="Scroll to trigger lazy-loaded content")
    content.add_argument("--wait-until", choices=["domcontentloaded", "load", "networkidle"])
    content.add_argument("--wait-for-selector", help="Cloak only: CSS selector to wait for")
    content.add_argument("--proxy-profile", default="current")
    content.add_argument(
        "--format",
        choices=["json", "html", "markdown"],
        default="json",
        help="json prints full results; html/markdown print just that field (single URL only)",
    )
    content.set_defaults(handler=_cmd_content)

    asset = sub.add_parser("asset", help="Download an asset, optionally resized/re-encoded")
    asset.add_argument("url")
    asset.add_argument("--output-format", help="e.g. 'JPG,98' or 'WEBP,85'")
    asset.add_argument("--max-width", type=int)
    asset.add_argument("--max-height", type=int)
    asset.add_argument("-o", "--output", help="Write decoded bytes to file ('-' for stdout)")
    asset.set_defaults(handler=_cmd_asset)

    export = sub.add_parser("export", help="Render a URL or HTML file to PDF/PNG")
    export.add_argument("--url")
    export.add_argument("--html-file")
    export.add_argument("--type", choices=["pdf", "png"], default="pdf")
    export.add_argument("--request", help="JSON file with a full export request body (overrides other flags)")
    export.add_argument("-o", "--output", help="Output file (default: stdout)")
    export.set_defaults(handler=_cmd_export)

    actions = sub.add_parser("actions", help="Run a stateless browser action from a JSON request")
    actions.add_argument("--request", required=True, help="JSON file with the action request body ('-' for stdin)")
    actions.set_defaults(handler=_cmd_actions)

    status = sub.add_parser("status", help="Check proxy profile connectivity")
    status.add_argument("--proxy-profile", default="current")
    status.set_defaults(handler=_cmd_status)

    agent = sub.add_parser("agent", help="Print the agent-facing API documentation")
    agent.set_defaults(handler=_cmd_agent)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], Coroutine[Any, Any, int]] = args.handler
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
