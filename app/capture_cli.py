"""Pure CLI entry point for Scrapi's CloakBrowser evidence capture."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.browser_capture import BrowserCaptureError, BrowserCaptureRequest, capture_browser
from app.proxy_profiles import ProxyProfileError, resolve_proxy_profile


def _viewport(raw: str) -> tuple[int, int]:
    try:
        width, height = (int(value) for value in raw.lower().split("x", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("viewport must look like 1440x1000") from exc
    if width < 320 or height < 240:
        raise argparse.ArgumentTypeError("viewport must be at least 320x240")
    return width, height


def add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", metavar="URL", help="HTTP(S) page to capture")
    parser.add_argument("-o", "--output-dir", required=True, metavar="DIR")
    parser.add_argument("--viewport", type=_viewport, default=(1440, 1000), metavar="WIDTHxHEIGHT")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--proxy-profile", default="current", metavar="NAME")
    parser.add_argument("--geoip", action="store_true", help="Match timezone/locale/WebRTC to proxy exit")
    parser.add_argument("--no-humanize", action="store_true")
    parser.add_argument("--human-preset", choices=("default", "careful"), default="default")
    parser.add_argument(
        "--wait-until", choices=("auto", "load", "domcontentloaded", "networkidle", "commit"), default="auto"
    )
    parser.add_argument("--wait-for-selector")
    parser.add_argument("--navigation-timeout-ms", type=int, default=30_000)
    parser.add_argument("--networkidle-timeout-ms", type=int, default=10_000)
    parser.add_argument("--hard-timeout-seconds", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2, help="Fresh-process retries after the first attempt")
    parser.add_argument("--keep-cookie-banners", action="store_true")
    parser.add_argument("--no-adblock", action="store_true")
    parser.add_argument("--scroll-full", action="store_true")
    parser.add_argument("--max-scroll-steps", type=int, default=60)
    parser.add_argument("--screenshot", choices=("full", "viewport", "off"), default="full")
    parser.add_argument("--screenshot-format", choices=("png", "jpeg"), default="png")
    parser.add_argument("--screenshot-quality", type=int, choices=range(101), default=98, metavar="0-100")
    parser.add_argument("--max-screenshot-height", type=int, default=20_000, metavar="PIXELS")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--no-har", action="store_true")
    parser.add_argument("--resources", choices=("none", "media", "assets", "all"), default="none")
    parser.add_argument("--max-resource-mib", type=int, default=20)
    parser.add_argument("--max-total-resource-mib", type=int, default=100)


async def run_capture(args: argparse.Namespace) -> int:
    try:
        proxy_url = resolve_proxy_profile(args.proxy_profile)
    except ProxyProfileError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    width, height = args.viewport
    request = BrowserCaptureRequest(
        url=args.url,
        output_dir=str(Path(args.output_dir).resolve()),
        width=width,
        height=height,
        headed=args.headed,
        proxy_url=proxy_url,
        geoip=args.geoip,
        humanize=not args.no_humanize,
        human_preset=args.human_preset,
        wait_until=args.wait_until,
        wait_for_selector=args.wait_for_selector,
        navigation_timeout_ms=args.navigation_timeout_ms,
        networkidle_timeout_ms=args.networkidle_timeout_ms,
        hard_timeout_seconds=args.hard_timeout_seconds,
        retries=args.retries,
        cookie_mode="keep" if args.keep_cookie_banners else "dismiss",
        adblock=not args.no_adblock,
        scroll_full=args.scroll_full,
        max_scroll_steps=args.max_scroll_steps,
        screenshot=args.screenshot,
        screenshot_format=args.screenshot_format,
        screenshot_quality=args.screenshot_quality,
        max_screenshot_height=args.max_screenshot_height,
        html=not args.no_html,
        har=not args.no_har,
        video=args.video,
        resources=args.resources,
        max_resource_bytes=args.max_resource_mib * 1024 * 1024,
        max_total_resource_bytes=args.max_total_resource_mib * 1024 * 1024,
    )
    try:
        result = await capture_browser(request)
    except BrowserCaptureError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrapi-capture",
        description="Capture screenshot, video, HAR, DOM, and resources through Scrapi's CloakBrowser stack.",
        epilog="""examples:
  python -m app.capture_cli https://example.com -o _tmp/example
  python -m app.capture_cli https://example.com -o _tmp/example --video --scroll-full
  python -m app.capture_cli https://example.com -o _tmp/example --resources assets
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_capture_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_capture(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
