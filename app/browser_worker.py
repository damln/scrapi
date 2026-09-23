"""Helpers shared by the CloakBrowser subprocess workers."""

from __future__ import annotations

from typing import Any

from cloakbrowser import launch

from app.config import PROXY_URL


def launch_cloak_browser():
    launch_kwargs: dict[str, Any] = {"humanize": True}
    if PROXY_URL:
        launch_kwargs["proxy"] = PROXY_URL
    return launch(**launch_kwargs)


def compact_error(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else exc.__class__.__name__
