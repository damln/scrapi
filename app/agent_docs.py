from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI

from app.agent_examples import curl_examples, response_examples
from app.config import SCRAPI_BASE_URL
from app.fetcher import DEFAULT_PROVIDER_ORDER
from app.recipes import RECIPE_PARAM_MODELS

ENDPOINT_NOTES = {
    "/api/v1/content": [
        "Use first for web page content. Read results[].markdown first; use results[].html for structured extraction.",
        "YouTube results include the preferred English transcript plus every available native-language track.",
        f"Default provider_order is {','.join(DEFAULT_PROVIDER_ORDER)}. Omit provider_order on the first attempt.",
        "Cloak supports proxy_profile=current|direct|<env-defined-name>; never pass raw proxy URLs.",
    ],
    "/api/v1/asset": [
        "Downloads an image asset and returns JSON with base64 data plus content metadata.",
    ],
    "/api/v1/export": [
        "Renders url or html to binary PDF/PNG. Response body is the file bytes, not JSON.",
    ],
    "/api/v1/capture": [
        "Runs the Scrapi CloakBrowser stack and returns a ZIP containing result.json plus requested screenshot, WebM, HAR, rendered HTML, and resources.",
        "Cookie dismissal, ad blocking, retries, and hard process cleanup are enabled by default.",
    ],
    "/api/v1/screenshot": [
        "Returns one JPEG directly, or a ZIP when viewport is repeated.",
        "Use viewport=mobile or viewport=desktop presets, or WIDTHxHEIGHT. Full-page height and lazy scrolling are bounded.",
    ],
    "/api/v1/actions": [
        "Runs a stateless browser action. The caller supplies cookies/session on every request.",
    ],
    "/api/v1/status": [
        "Public status endpoint for proxy/config health.",
    ],
    "/api/v1/agent": [
        "This public live document. Generated from current route and model metadata.",
    ],
}


def render_agent_markdown(app: FastAPI) -> str:
    openapi = app.openapi()
    components = openapi.get("components", {}).get("schemas", {})
    request_examples = curl_examples()
    returned_examples = response_examples()
    lines = [
        "# Scrapi API",
        "",
        f"base_url: {SCRAPI_BASE_URL}",
        "auth: Authorization: Bearer $SCRAPI_API_TOKEN except public endpoints and direct local/Docker calls",
        "source: live FastAPI/OpenAPI + Pydantic schemas generated at request time",
        "",
        "## Rules",
        "- First content fetch: omit provider_order unless retrying a known failure.",
        f"- Providers now: {', '.join(DEFAULT_PROVIDER_ORDER)}.",
        "- For JS-heavy cloak retries: provider_order=cloak&wait_until=networkidle&wait_for_selector=main&scroll_full=true.",
        "- Firecrawl is paid; use it only after cloak/auto returns weak or blocked content.",
        "",
        "## Endpoints",
    ]

    for path, methods in sorted(openapi.get("paths", {}).items()):
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in sorted(methods.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            lines.extend(
                _render_operation(
                    method.upper(),
                    path,
                    operation,
                    components,
                    request_examples,
                    returned_examples,
                )
            )

    lines.extend(_render_recipes(components))
    return "\n".join(lines).strip() + "\n"


def _render_operation(
    method: str,
    path: str,
    operation: dict[str, Any],
    components: dict[str, Any],
    request_examples: dict[str, list[str]],
    returned_examples: dict[str, object],
) -> list[str]:
    title = f"{method} {path}"
    lines = ["", f"### {title}"]
    security = operation.get("security")
    lines.append(f"auth: {'Bearer required except direct local/Docker calls' if security else 'public'}")

    for note in ENDPOINT_NOTES.get(path, []):
        lines.append(f"- {note}")

    params = operation.get("parameters") or []
    if params:
        lines.append("query:")
        for param in params:
            lines.append(_render_parameter(param))

    body_schema = _request_body_schema(operation)
    if body_schema is not None:
        schema_name, schema = _resolve_schema(body_schema, components)
        lines.append(f"body: {schema_name}")
        lines.extend(_render_schema_fields(schema, components, indent="  "))

    example = request_examples.get(title)
    if example:
        lines.append("example:")
        lines.append("```sh")
        lines.extend(example)
        lines.append("```")

    returned = returned_examples.get(title)
    if returned is not None:
        lines.append("returns example:")
        lines.append("```json")
        lines.append(json.dumps(returned, indent=2, sort_keys=True))
        lines.append("```")

    return lines


def _render_parameter(param: dict[str, Any]) -> str:
    schema = param.get("schema", {})
    required = "required" if param.get("required") else "optional"
    details = _schema_details(schema, include_description=False)
    description = param.get("description") or schema.get("description")
    suffix = f"; {description}" if description else ""
    return f"- {param['name']} ({required}): {details}{suffix}"


def _request_body_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    content = (operation.get("requestBody") or {}).get("content") or {}
    json_body = content.get("application/json") or {}
    return json_body.get("schema")


def _resolve_schema(schema: dict[str, Any], components: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return name, components.get(name, schema)
    return schema.get("title") or "inline", schema


def _render_schema_fields(
    schema: dict[str, Any],
    components: dict[str, Any],
    *,
    indent: str = "",
    seen: set[str] | None = None,
) -> list[str]:
    seen = seen or set()
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines: list[str] = []
    nested_refs: list[tuple[str, dict[str, Any]]] = []

    for name, prop_schema in properties.items():
        lines.append(
            f"{indent}- {name} ({'required' if name in required else 'optional'}): {_schema_details(prop_schema)}"
        )
        for ref_name, ref_schema in _find_direct_refs(prop_schema, components):
            if ref_name not in seen:
                nested_refs.append((ref_name, ref_schema))

    for ref_name, ref_schema in nested_refs:
        seen.add(ref_name)
        lines.append(f"{indent}- {ref_name}:")
        lines.extend(_render_schema_fields(ref_schema, components, indent=f"{indent}  ", seen=seen))

    return lines


def _find_direct_refs(schema: dict[str, Any], components: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    refs: list[tuple[str, dict[str, Any]]] = []
    for candidate in _iter_schema_nodes(schema):
        ref = candidate.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            refs.append((name, components.get(name, candidate)))
    return refs


def _iter_schema_nodes(schema: dict[str, Any]):
    yield schema
    for key in ("anyOf", "oneOf", "allOf"):
        for item in schema.get(key) or []:
            yield from _iter_schema_nodes(item)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _iter_schema_nodes(items)


def _schema_details(schema: dict[str, Any], *, include_description: bool = True) -> str:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]

    if "anyOf" in schema:
        types = [_schema_details(item, include_description=include_description) for item in schema["anyOf"]]
        return " | ".join(types)

    if "allOf" in schema:
        types = [_schema_details(item, include_description=include_description) for item in schema["allOf"]]
        return " & ".join(types)

    if "enum" in schema:
        return "enum[" + ", ".join(map(str, schema["enum"])) + "]" + _default_suffix(schema)

    schema_type = schema.get("type") or schema.get("title") or "object"
    if schema_type == "array":
        item_type = _schema_details(schema.get("items") or {})
        schema_type = f"array<{item_type}>"
    elif schema_type == "object" and schema.get("additionalProperties"):
        schema_type = "object/map"

    constraints = _constraints(schema)
    description = schema.get("description")
    parts = [schema_type + _default_suffix(schema)]
    if constraints:
        parts.append(constraints)
    if include_description and description:
        parts.append(description)
    return "; ".join(parts)


def _default_suffix(schema: dict[str, Any]) -> str:
    if "default" not in schema:
        return ""
    return f" default={json.dumps(schema['default'])}"


def _constraints(schema: dict[str, Any]) -> str:
    pairs = [
        ("minimum", "min"),
        ("maximum", "max"),
        ("exclusiveMinimum", "exclusive_min"),
        ("exclusiveMaximum", "exclusive_max"),
        ("minLength", "min_len"),
        ("maxLength", "max_len"),
        ("minItems", "min_items"),
        ("maxItems", "max_items"),
    ]
    values = [f"{label}={schema[key]}" for key, label in pairs if key in schema]
    return ", ".join(values)


def _render_recipes(components: dict[str, Any]) -> list[str]:
    lines = ["", "## Action Recipes"]
    for name, model in sorted(RECIPE_PARAM_MODELS.items()):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        lines.append("")
        lines.append(f"### {name} params")
        lines.extend(_render_schema_fields(schema, components, indent=""))
    return lines
