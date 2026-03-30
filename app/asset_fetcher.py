import base64
import io

import httpx
from PIL import Image

from app.config import FETCH_TIMEOUT_MS

MAX_ASSET_BYTES = 20 * 1024 * 1024  # 20MB

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

_FORMAT_TO_CONTENT_TYPE = {
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "PNG": "image/png",
    "GIF": "image/gif",
}

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    _client = httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(FETCH_TIMEOUT_MS / 1000),
    )


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _is_raster_image(content_type: str) -> bool:
    return content_type.startswith("image/") and content_type != "image/svg+xml"


def _parse_output_format(output_format: str | None) -> tuple[str | None, int | None]:
    if not output_format:
        return None, None
    parts = output_format.upper().split(",", 1)
    fmt = parts[0].strip()
    if fmt == "JPG":
        fmt = "JPEG"
    quality = int(parts[1].strip()) if len(parts) > 1 else None
    return fmt, quality


def _process_image(
    data: bytes,
    content_type: str,
    output_format: str | None,
    max_width: int | None,
    max_height: int | None,
) -> tuple[bytes, str, str, int, int]:
    fmt, quality = _parse_output_format(output_format)

    img = Image.open(io.BytesIO(data))

    is_animated = getattr(img, "is_animated", False)
    needs_transform = fmt is not None or max_width is not None or max_height is not None

    if is_animated and not needs_transform:
        w, h = img.size
        return data, content_type, img.format or "GIF", w, h

    target_format = fmt or img.format or "PNG"

    if target_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode == "P" and target_format != "GIF":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")

    if max_width or max_height:
        img.thumbnail(
            (max_width or 99999, max_height or 99999),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    save_kwargs = {"format": target_format}
    if target_format in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality if quality is not None else 85
    if target_format == "JPEG":
        save_kwargs["optimize"] = True

    img.save(buf, **save_kwargs)
    processed = buf.getvalue()

    w, h = img.size
    new_content_type = _FORMAT_TO_CONTENT_TYPE.get(target_format, f"image/{target_format.lower()}")

    return processed, new_content_type, target_format, w, h


def _extract_http_metadata(resp: httpx.Response) -> dict:
    """Extract HTTP status, headers, and redirect history from an httpx response."""
    history = []
    for r in resp.history:
        history.append({
            "status": r.status_code,
            "url": str(r.url),
            "headers": dict(r.headers),
        })

    return {
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "redirect_history": history if history else None,
    }


async def _fetch_asset_bytes(url: str) -> tuple[bytes, str, dict]:
    resp = await _client.get(url)
    resp.raise_for_status()

    raw_ct = resp.headers.get("content-type", "application/octet-stream")
    content_type = raw_ct.split(";")[0].strip().lower()

    data = resp.content
    if len(data) > MAX_ASSET_BYTES:
        raise RuntimeError(f"Asset too large: {len(data)} bytes (max {MAX_ASSET_BYTES})")
    if not data:
        raise RuntimeError("Empty response body")

    http_metadata = _extract_http_metadata(resp)
    return data, content_type, http_metadata


async def fetch_and_process_asset(
    url: str,
    output_format: str | None,
    max_width: int | None,
    max_height: int | None,
) -> dict:
    try:
        data, content_type, http_metadata = await _fetch_asset_bytes(url)

        if _is_raster_image(content_type):
            processed, new_ct, fmt_name, w, h = _process_image(
                data, content_type, output_format, max_width, max_height,
            )
            return {
                "url": url,
                "status": "success",
                "content_type": new_ct,
                "format": fmt_name,
                "width": w,
                "height": h,
                "data": base64.b64encode(processed).decode("ascii"),
                "http": http_metadata,
            }

        return {
            "url": url,
            "status": "success",
            "content_type": content_type,
            "data": base64.b64encode(data).decode("ascii"),
            "http": http_metadata,
        }

    except Exception as exc:
        return {
            "url": url,
            "status": "error",
            "error": str(exc),
        }
