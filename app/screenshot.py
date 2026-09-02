from __future__ import annotations

import copy
import json
import re
import zipfile
from pathlib import Path
from typing import Any

MAX_SCREENSHOTS_PER_REQUEST = 5
VIEWPORT_PRESETS = {
    "desktop": (1440, 1000),
    "mobile": (390, 844),
}


def parse_viewports(values: list[str] | None) -> list[tuple[int, int]]:
    requested = values or ["desktop"]
    if len(requested) > MAX_SCREENSHOTS_PER_REQUEST:
        raise ValueError(f"at most {MAX_SCREENSHOTS_PER_REQUEST} viewports are allowed")

    viewports = []
    for raw in requested:
        value = raw.strip().lower()
        if value in VIEWPORT_PRESETS:
            viewport = VIEWPORT_PRESETS[value]
        else:
            match = re.fullmatch(r"(\d+)x(\d+)", value)
            if not match:
                raise ValueError("viewport must be desktop, mobile, or WIDTHxHEIGHT")
            viewport = (int(match.group(1)), int(match.group(2)))
        width, height = viewport
        if not 320 <= width <= 7680 or not 240 <= height <= 7680:
            raise ValueError("viewport width must be 320-7680 and height must be 240-7680")
        if viewport not in viewports:
            viewports.append(viewport)
    return viewports


def build_screenshot_archive(captures: list[dict[str, Any]], archive_path: Path) -> None:
    manifest = []
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for capture in captures:
            portable = copy.deepcopy(capture)
            screenshot_path = Path(portable["files"]["screenshot"])
            viewport = portable["viewport"]
            filename = f'screenshot-{viewport["width"]}x{viewport["height"]}.jpg'
            portable["files"]["screenshot"] = filename
            archive.write(screenshot_path, filename)
            manifest.append(portable)
        archive.writestr("result.json", json.dumps({"results": manifest}, indent=2))
