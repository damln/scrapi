# Scrapi

FastAPI API that fetches full HTML content from URLs using Scrapling's StealthyFetcher for stealth browser rendering.

## Stack

- Python 3.12
- FastAPI
- Scrapling (StealthyFetcher) for stealth headless browsing
- Docker for development and production

## Running

```bash
docker compose -f docker-compose.dev.yml up --build
```

## API

### `GET /`

Returns `ok` (plain text). No auth required.

### `GET /health`

Returns `ok` (plain text). No auth required. Used by Docker healthcheck.

### `GET /api/v1/content`

Fetch full HTML content from one or more URLs.

**Auth:** Bearer token in `Authorization` header.

**Query params:**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `urls` | string (repeated) | yes | — | URLs to fetch. Repeat for multiple: `urls=...&urls=...` |
| `no_style` | bool | no | `false` | Remove all inline `style="..."` attributes |
| `no_script` | bool | no | `false` | Remove all inline `<script>` tags (without `src` attribute) |
| `provider_order` | string | no | `raw,cloudflare,firecrawl` | Comma-separated provider order |
| `scroll_full` | bool | no | `false` | Scroll full page incrementally to trigger lazy-loaded content. Adds ~5–20s. Supported by `raw` and `cloudflare`; no-op for `firecrawl`. |

**Max 10 URLs per request.**

**Valid providers:** `raw`, `cloudflare`, `firecrawl`

**Response:**

```json
{
  "results": [
    {
      "url": "https://example.com/page?color=red",
      "raw_url": "https://example.com/page?utm_source=google&color=red",
      "status": "success",
      "provider": "raw",
      "html": "<!DOCTYPE html>...",
      "scores": {
        "html_length": 45230,
        "has_body": true,
        "blocked_matches": []
      }
    }
  ]
}
```

**Error response (per URL):**

```json
{
  "url": "https://example.com",
  "raw_url": "https://example.com",
  "status": "error",
  "provider": null,
  "error": "All providers failed to fetch valid content",
  "html": null
}
```

### `GET /api/v1/asset`

Download a single asset (image, CSS, JS) and return it as base64-encoded data.

**Auth:** Bearer token in `Authorization` header.

**Query params:**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | yes | — | Asset URL to download |
| `output_format` | string | no | — | Image format + quality: `"JPG,98"`, `"WEBP,85"`, `"PNG"`. Quality optional (default 85). Ignored for CSS/JS/SVG. |
| `max_width` | int | no | — | Max width in px. Aspect ratio preserved, never upscales. Ignored for CSS/JS/SVG. |
| `max_height` | int | no | — | Max height in px. Aspect ratio preserved, never upscales. Ignored for CSS/JS/SVG. |

**Response (image):**

```json
{
  "url": "https://example.com/photo.webp",
  "status": "success",
  "content_type": "image/jpeg",
  "format": "JPEG",
  "width": 1920,
  "height": 1080,
  "data": "<base64>"
}
```

**Response (CSS/JS/SVG):**

```json
{
  "url": "https://example.com/style.css",
  "status": "success",
  "content_type": "text/css",
  "data": "<base64>"
}
```

**Error response:**

```json
{
  "url": "https://example.com/image.png",
  "status": "error",
  "error": "HTTP 403 fetching asset"
}
```

**Notes:**
- Uses httpx (not browser) for fast fetching — most CDN assets don't need stealth
- Max asset size: 20MB
- Supported image formats: PNG, JPEG, WEBP, GIF, and any format Pillow can open
- SVG is passed through as-is (no raster processing)
- Animated GIFs are passed through unchanged unless a transform is requested

### URL Cleaning

Before fetching, all URLs are cleaned:
- **Tracking params stripped**: UTM, fbclid, gclid, msclkid, and 40+ other tracking parameters are removed
- **Query params sorted alphabetically**: ensures consistent URLs for future cache hits
- Response includes both `url` (cleaned) and `raw_url` (original input)

### Fallback Chain

Default order: `raw` → `cloudflare` → `firecrawl`

1. **raw** (Scrapling, 15s timeout) — stealth browser fetch, validates content is not a block page
2. **cloudflare** (Cloudflare Browser Rendering) — fallback if raw content is blocked/empty
3. **firecrawl** (Firecrawl API) — last resort, returns content without validation

Override with `provider_order` param (comma-separated):

```
GET /api/v1/content?urls=https://example.com&provider_order=firecrawl,cloudflare
GET /api/v1/content?urls=https://example.com&provider_order=raw
```

### Content Validation

Each provider (except the last in the chain) validates the fetched HTML:
- HTML must be at least 256 bytes
- Must contain a `<body>` tag
- Must not match 2+ block/captcha indicators (access denied, captcha, cloudflare challenge, etc.)

The last provider in the chain returns whatever it fetched, even if validation fails.

## Test

Single URL:

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/content?urls=https://damln.com"

curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/content?urls=https://www.airbnb.com/rooms/1390463594335012333?check_in=2026-07-10&check_out=2026-07-12&photo_id=2198427852&source_impression_id=p3_1774637206_P3sg_i0zJQ6efoL-&previous_page_section_name=1000"

curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/content?urls=https://www.nytimes.com/spotlight/lifestyle"
```

Multiple URLs (repeat the `urls` param):

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/content?urls=https://damln.com&urls=https://example.com&urls=https://other.com"
```

Asset download (image):

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/asset?url=https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png"
```

Asset download with format conversion and resize:

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/asset?url=https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png&output_format=JPG,95&max_width=800"
```

Asset download (CSS):

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/asset?url=https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
```

With lazy-load scrolling (for pages that load content on scroll):

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:10700/api/v1/content?urls=https://www.coches.net/segunda-mano/&scroll_full=true"
```

## Cookie/Popup Dismissal

Automatic cookie consent and popup dismissal using cosmetic filter lists injected via Scrapling's `page_action` callback.

**How it works (4 layers):**
1. CSS cosmetic filters hide banners (33K+ selectors)
2. MutationObserver JS catches dynamically injected banners
3. Fallback clicks on known accept buttons (OneTrust, Cookiebot, etc.)
4. DOM cleanup removes leftover banner elements

**Filter list sources:**
- EasyList Fanboy Annoyance: `https://easylist-downloads.adblockplus.org/fanboy-annoyance.txt`
- I Don't Care About Cookies: `https://www.i-dont-care-about-cookies.eu/abp/`

These are AdBlock Plus format filter lists. The parser (`app/cookie_dismiss/filter_parser.py`) extracts generic cosmetic rules (lines starting with `##`) and generates CSS + JS assets.

**Update filter lists:**

```bash
python scripts/update_cookie_filters.py
```

This downloads the latest lists and regenerates `app/cookie_dismiss/cosmetic_filters.css` and `app/cookie_dismiss/observer.js`. Run periodically to stay current.

**Key constraint:** The `page_action` callback must be sync and must `return page` — Scrapling reassigns the return value internally.

## Lazy-Load Scrolling

When `scroll_full=true` is passed, providers scroll the full page incrementally after the initial page load to trigger intersection-observer-based lazy loading (e.g. coches.net search results, infinite-scroll listing pages).

**Raw provider (Scrapling):**
- Scrolls in 800px increments via `window.scrollTo`
- Waits 400ms between each step (for XHR/fetch triggers to fire)
- Stops early when page height stabilizes after reaching the bottom
- Capped at 40 iterations (~32 000px max depth)
- 1500ms network settle wait after the last scroll step
- Adds roughly 5–20s to raw fetch time

**Cloudflare provider:**
- Injects an async IIFE via `addScriptTag` that mirrors the same scroll loop
- Adds `waitForTimeout: 20500` (ms) to give the script time to complete
- Requires `CLOUDFLARE_TIMEOUT_SECONDS` >= 30 (default satisfies this)

**Firecrawl provider:** No scroll support — `scroll_full` is ignored.

## Ad/Tracker Blocking

Built-in via Scrapling's `disable_ads=True` parameter, which installs **uBlock Origin** as a Firefox addon in the Camoufox browser. This blocks ads, trackers, and analytics at the network level — no custom domain lists needed.

## Deployment

For production deployment to the server, use the `damian-server` skill (`/damian-server`). It covers the full Docker Swarm deploy flow, config resolution via `os.yml` + `os_config.yml`, and all common pitfalls.

## NanoClaw (MacBook Air) Setup

Scrapi also runs on the MacBook Air at `~/scrapi` for local use. From other Docker containers on the same host (e.g. NanoClaw agents), reach it at:

```
http://host.docker.internal:10700
```

**Update to latest version:**

```bash
cd ~/scrapi && git pull && docker compose -f docker-compose.dev.yml up --build -d
```

## Environment Variables

- `SCRAPI_API_TOKEN` — required, the bearer token for API auth
- `SCRAPI_FETCH_TIMEOUT_MS` — optional, fetch timeout in ms (default: 30000)
- `FIRECRAWL_API_KEY` — Firecrawl API key
- `CLOUDFLARE_API_KEY` — Cloudflare API key
- `CLOUDFLARE_ACCOUNT_ID` — Cloudflare account ID
