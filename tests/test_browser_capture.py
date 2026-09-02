import json
import zipfile
from pathlib import Path

import pytest

from app.browser_capture import BrowserCaptureApiRequest, BrowserCaptureRequest, build_capture_archive
from app.browser_capture_worker import RESOURCE_TYPES, ResourceCollector, _capture_screenshot, _safe_name
from app.capture_cli import build_parser


def test_capture_cli_exposes_evidence_and_runtime_controls():
    help_text = build_parser().format_help()
    for option in (
        "--video",
        "--screenshot",
        "--screenshot-format",
        "--screenshot-quality",
        "--render-scale",
        "--max-screenshot-height",
        "--resources",
        "--scroll-full",
        "--keep-cookie-banners",
        "--proxy-profile",
        "--hard-timeout-seconds",
        "--retries",
    ):
        assert option in help_text


def test_capture_request_defaults_to_scrapi_protections():
    request = BrowserCaptureRequest("https://example.com", "/tmp/evidence")
    assert request.cookie_mode == "dismiss"
    assert request.adblock is True
    assert request.humanize is True
    assert request.retries == 2
    assert request.screenshot_format == "png"
    assert request.render_scale == 1
    assert request.max_screenshot_height == 20_000


def test_api_request_builds_internal_request_without_exposing_output_path(tmp_path: Path):
    request = BrowserCaptureApiRequest(url="https://example.com", resources="assets")
    internal = request.to_capture_request(str(tmp_path), "socks5://proxy:1080")
    assert internal.output_dir == str(tmp_path)
    assert internal.proxy_url == "socks5://proxy:1080"
    assert internal.resources == "assets"


def test_resource_modes_are_monotonic():
    assert RESOURCE_TYPES["none"] < RESOURCE_TYPES["media"]
    assert RESOURCE_TYPES["media"] < RESOURCE_TYPES["assets"]
    assert RESOURCE_TYPES["assets"] < RESOURCE_TYPES["all"]


def test_safe_resource_name_is_bounded_and_url_specific():
    first = _safe_name("https://cdn.example.com/a/hero image.jpg?size=2", 0)
    second = _safe_name("https://other.example.com/a/hero image.jpg?size=2", 0)
    assert first.endswith(".jpg")
    assert first != second
    assert len(first) < 120


def test_resource_collector_writes_manifest_for_empty_capture(tmp_path: Path):
    collector = ResourceCollector(tmp_path / "resources", "media", 100, 1000)
    manifest = collector.write_manifest()
    assert manifest is not None
    assert Path(manifest).is_file()


def test_jpeg_full_page_screenshot_is_capped(tmp_path: Path):
    class FakePage:
        screenshot_options = None

        def evaluate(self, script):
            return None if "scrollTo" in script else 30_000

        def screenshot(self, **options):
            self.screenshot_options = options

    page = FakePage()
    request = {
        "screenshot_format": "jpeg",
        "screenshot_quality": 98,
        "screenshot": "full",
        "max_screenshot_height": 20_000,
    }

    metadata = _capture_screenshot(page, request, tmp_path / "screenshot.jpg", 1440, 1000)

    assert metadata["capped"] is True
    assert metadata["height"] == 20_000
    assert page.screenshot_options["quality"] == 98
    assert page.screenshot_options["clip"] == {"x": 0, "y": 0, "width": 1440, "height": 20_000}


def test_retina_jpeg_is_downsampled_to_requested_dimensions(tmp_path: Path):
    class FakePage:
        screenshot_options = None

        def evaluate(self, script):
            return None if "scrollTo" in script else 1280

        def screenshot(self, **options):
            self.screenshot_options = options
            Image.new("RGB", (2560, 2560), "white").save(options["path"], format="PNG")

    from PIL import Image

    page = FakePage()
    path = tmp_path / "screenshot.jpg"
    request = {
        "screenshot_format": "jpeg",
        "screenshot_quality": 99,
        "render_scale": 2,
        "screenshot": "viewport",
        "max_screenshot_height": 3000,
    }

    metadata = _capture_screenshot(page, request, path, 1280, 1280)

    with Image.open(path) as screenshot:
        assert screenshot.size == (1280, 1280)
        assert screenshot.format == "JPEG"
    assert metadata["render_scale"] == 2
    assert page.screenshot_options["scale"] == "device"
    assert page.screenshot_options["type"] == "png"
    assert not (tmp_path / "screenshot.retina.png").exists()


def test_capture_archive_rewrites_artifact_paths(tmp_path: Path):
    evidence = tmp_path / "evidence"
    resources = evidence / "resources"
    resources.mkdir(parents=True)
    screenshot = evidence / "screenshot.png"
    screenshot.write_bytes(b"png")
    asset = resources / "hero.jpg"
    asset.write_bytes(b"jpg")
    manifest = resources / "manifest.json"
    manifest.write_text(json.dumps({"resources": [{"path": str(asset)}]}))
    archive_path = tmp_path / "capture.zip"

    portable = build_capture_archive(
        {"status": "success", "files": {"screenshot": str(screenshot), "resource_manifest": str(manifest)}},
        evidence,
        archive_path,
    )

    assert portable["files"]["screenshot"] == "screenshot.png"
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {
            "result.json",
            "resources/hero.jpg",
            "resources/manifest.json",
            "screenshot.png",
        }
        archived_manifest = json.loads(archive.read("resources/manifest.json"))
        assert archived_manifest["resources"][0]["path"] == "resources/hero.jpg"


@pytest.mark.parametrize("viewport", ["100x100", "bad", "1440"])
def test_capture_cli_rejects_invalid_viewport(viewport):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["https://example.com", "-o", "/tmp/out", "--viewport", viewport])
