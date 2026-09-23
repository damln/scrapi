"""Action recipes registry.

Each recipe is a function ``fn(page, req: dict, log: list[str]) -> dict`` that
drives an already-logged-in page (cookies injected by the worker). One module
per platform so new platforms slot in without touching the worker.
"""

from __future__ import annotations

from app.recipes.twitter import XPostParams, x_post

RECIPES = {
    "x_post": x_post,
}

RECIPE_PARAM_MODELS = {
    "x_post": XPostParams,
}

__all__ = ["RECIPES", "RECIPE_PARAM_MODELS"]
