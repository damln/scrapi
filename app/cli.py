"""Command-line interface — the full scraping pipeline without HTTP.

Runs the same code paths as the API endpoints (provider fallback chain,
content validation, markdown conversion, PDF/PNG export, browser
actions) directly in-process. No server, no SCRAPI_API_TOKEN needed.

Usage (from the repo, a venv, or inside the Docker image):

    python -m app.cli content https://example.com
    python -m app.cli content https://example.com --format markdown
    python -m app.cli asset https://example.com/logo.png -o logo.png
    python -m app.cli export --url https://example.com -o page.pdf
    python -m app.cli capture https://example.com -o _tmp/example --video
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

HELP_FORMATTER = argparse.RawDescriptionHelpFormatter

CLI_DESCRIPTION = """\
Run Scrapi's full scraping pipeline directly, without starting the HTTP server.

Content results include cleaned HTML, markdown, and head metadata. Captcha or shell
pages fail validation so the next provider can be tried. Asset processing, PDF/PNG
rendering, and browser actions use the same code paths as the API.
SCRAPI_API_TOKEN is not required for CLI commands."""

CLI_EPILOG = f"""\
quick start:
  python -m app.cli content https://example.com
  python -m app.cli content https://example.com --format markdown
  python -m app.cli asset https://example.com/logo.png --max-width 800 -o logo.png
  python -m app.cli export --url https://example.com -o page.pdf
  python -m app.cli capture https://example.com -o _tmp/example --scroll-full
  python -m app.cli actions --request action.json
  python -m app.cli status
  python -m app.cli agent > scrapi-api.md

output behavior:
  content   JSON by default; --format html/markdown prints one URL's content
  asset     JSON with base64 data by default; -o writes decoded bytes
  export    binary PDF/PNG to stdout by default; -o writes a file
  capture   screenshot/video/HAR/DOM/resources to an evidence directory
  actions   JSON result and browser action log
  status    JSON proxy-connectivity report
  agent     complete agent-facing API docs and request schemas as markdown

providers and configuration:
  Default page providers: {", ".join(DEFAULT_PROVIDER_ORDER)}.
  Cloak is local and keyless; Firecrawl is enabled by FIRECRAWL_API_KEY.
  Twitter/X and YouTube URLs use dedicated keyless fetchers.
  No proxy is required. PROXY_URL configures the "current" proxy profile;
  SCRAPI_PROXY_PROFILES_JSON adds named profiles. "direct" always bypasses proxies.
  BROWSER_MAX_CONCURRENT limits concurrent Chromium instances (default: 2).

docker:
  docker run --rm scrapi python -m app.cli content https://example.com
  docker exec <container> python -m app.cli content https://example.com

discovery:
  python -m app.cli COMMAND --help   show options and examples for one command
  python -m app.cli agent            show full API schemas for export/actions
"""


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


async def _cmd_capture(args: argparse.Namespace) -> int:
    from app.capture_cli import run_capture

    return await run_capture(args)


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
    parser = argparse.ArgumentParser(
        prog="scrapi",
        description=CLI_DESCRIPTION,
        epilog=CLI_EPILOG,
        formatter_class=HELP_FORMATTER,
    )
    sub = parser.add_subparsers(dest="command", required=True, title="commands")

    content = sub.add_parser(
        "content",
        help="Fetch pages through the provider fallback chain",
        description="Fetch one or more pages, validate their content, and return cleaned HTML and markdown.",
        epilog="""\
examples:
  python -m app.cli content https://example.com
  python -m app.cli content https://example.com --format markdown
  python -m app.cli content https://one.example https://two.example
  python -m app.cli content https://example.com --provider-order cloak
  python -m app.cli content https://example.com --proxy-profile direct
""",
        formatter_class=HELP_FORMATTER,
    )
    content.add_argument("urls", nargs="+", metavar="URL", help="One or more HTTP(S) URLs to fetch")
    content.add_argument("--no-style", action="store_true", help="Remove inline style attributes")
    content.add_argument("--no-script", action="store_true", help="Remove script tags from returned HTML")
    content.add_argument(
        "--provider-order",
        metavar="PROVIDER,...",
        default=",".join(DEFAULT_PROVIDER_ORDER),
        help=(
            "Comma-separated fallback order. "
            f"Valid providers: {', '.join(DEFAULT_PROVIDER_ORDER)} (default: {','.join(DEFAULT_PROVIDER_ORDER)})"
        ),
    )
    content.add_argument("--scroll-full", action="store_true", help="Scroll to trigger lazy-loaded content")
    content.add_argument(
        "--wait-until",
        choices=["domcontentloaded", "load", "networkidle"],
        help="Cloak page-load readiness condition",
    )
    content.add_argument("--wait-for-selector", help="Cloak only: CSS selector to wait for")
    content.add_argument(
        "--proxy-profile",
        metavar="NAME",
        default="current",
        help="Proxy profile: current, direct, or a configured name (default: current)",
    )
    content.add_argument(
        "--format",
        choices=["json", "html", "markdown"],
        default="json",
        help="json prints full results; html/markdown print just that field (single URL only)",
    )
    content.set_defaults(handler=_cmd_content)

    asset = sub.add_parser(
        "asset",
        help="Download an asset, optionally resized/re-encoded",
        description="Fetch an image or other asset. Without -o, return JSON containing base64-encoded data.",
        epilog="""\
examples:
  python -m app.cli asset https://example.com/logo.png -o logo.png
  python -m app.cli asset https://example.com/photo.png --output-format WEBP,85 -o photo.webp
  python -m app.cli asset https://example.com/photo.jpg --max-width 800 -o photo.jpg
""",
        formatter_class=HELP_FORMATTER,
    )
    asset.add_argument("url", metavar="URL", help="HTTP(S) URL of the asset")
    asset.add_argument("--output-format", metavar="FORMAT[,QUALITY]", help="Re-encode an image, e.g. JPG,98 or WEBP,85")
    asset.add_argument("--max-width", type=int, metavar="PIXELS", help="Resize an image to at most this width")
    asset.add_argument("--max-height", type=int, metavar="PIXELS", help="Resize an image to at most this height")
    asset.add_argument("-o", "--output", metavar="FILE", help="Write decoded bytes to FILE; use - for stdout")
    asset.set_defaults(handler=_cmd_asset)

    export = sub.add_parser(
        "export",
        help="Render a URL or HTML file to PDF/PNG",
        description=(
            "Render exactly one URL or local HTML file. Use --request for advanced settings; "
            "the agent command documents its JSON schema."
        ),
        epilog="""\
examples:
  python -m app.cli export --url https://example.com -o page.pdf
  python -m app.cli export --html-file page.html --type png -o page.png
  python -m app.cli export --request export.json -o page.pdf
""",
        formatter_class=HELP_FORMATTER,
    )
    export.add_argument("--url", metavar="URL", help="HTTP(S) page URL to render")
    export.add_argument("--html-file", metavar="FILE", help="Local UTF-8 HTML file to render")
    export.add_argument("--type", choices=["pdf", "png"], default="pdf", help="Export format (default: pdf)")
    export.add_argument(
        "--request",
        metavar="FILE",
        help="JSON file with a full export request; overrides --url, --html-file, and --type",
    )
    export.add_argument("-o", "--output", metavar="FILE", help="Write output to FILE (default: binary stdout)")
    export.set_defaults(handler=_cmd_export)

    capture = sub.add_parser(
        "capture",
        help="Capture browser evidence through CloakBrowser",
        description=(
            "Capture screenshots, video, HAR, rendered DOM, and optional network resources while reusing "
            "Scrapi's CloakBrowser, ad blocking, cookie dismissal, proxy profiles, and process isolation."
        ),
        epilog="""\
examples:
  python -m app.cli capture https://example.com -o _tmp/example
  python -m app.cli capture https://example.com -o _tmp/example --video --scroll-full
  python -m app.cli capture https://example.com -o _tmp/example --resources assets
""",
        formatter_class=HELP_FORMATTER,
    )
    from app.capture_cli import add_capture_arguments

    add_capture_arguments(capture)
    capture.set_defaults(handler=_cmd_capture)

    actions = sub.add_parser(
        "actions",
        help="Run a stateless browser action from a JSON request",
        description=(
            "Run one browser action request and print its JSON result and log. "
            "Use the agent command to inspect the request schema and examples."
        ),
        epilog="""\
examples:
  python -m app.cli actions --request action.json
  cat action.json | python -m app.cli actions --request -
  python -m app.cli agent > scrapi-api.md
""",
        formatter_class=HELP_FORMATTER,
    )
    actions.add_argument(
        "--request",
        required=True,
        metavar="FILE",
        help="JSON action request file; use - to read JSON from stdin",
    )
    actions.set_defaults(handler=_cmd_actions)

    status = sub.add_parser(
        "status",
        help="Check proxy profile connectivity",
        description="Check connectivity through a configured proxy profile and print a JSON report.",
        epilog="""\
examples:
  python -m app.cli status
  python -m app.cli status --proxy-profile direct
""",
        formatter_class=HELP_FORMATTER,
    )
    status.add_argument(
        "--proxy-profile",
        metavar="NAME",
        default="current",
        help="Proxy profile: current, direct, or a configured name (default: current)",
    )
    status.set_defaults(handler=_cmd_status)

    agent = sub.add_parser(
        "agent",
        help="Print agent-facing API docs and request schemas",
        description="Print live markdown documentation generated from Scrapi's routes and Pydantic models.",
        epilog="""\
examples:
  python -m app.cli agent
  python -m app.cli agent > scrapi-api.md
""",
        formatter_class=HELP_FORMATTER,
    )
    agent.set_defaults(handler=_cmd_agent)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], Coroutine[Any, Any, int]] = args.handler
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
