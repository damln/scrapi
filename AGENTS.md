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
| `force_fetch` | bool | no | `false` | Bypass cache and force a fresh fetch. The result is still written to cache. |

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
      },
      "head_meta": {
        "title": "Example Page",
        "description": "An example page description",
        "og:title": "Example Page",
        "og:image": "https://example.com/image.png",
        "canonical": "https://example.com/page"
      },
      "markdown": "# Example Page\n\nThis is the page content...",
      "http": {
        "status": 200,
        "headers": {"content-type": "text/html; charset=utf-8", "...": "..."},
        "redirect_history": [
          {"status": 301, "url": "http://example.com/page", "headers": {"location": "https://example.com/page", "...": "..."}}
        ]
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

**Error response for Twitter/YouTube 404:**

When a Twitter/X or YouTube URL is confirmed as not found (404) by the dedicated fetcher, the API returns an error with the provider name and a `"Not found (404)"` message. This is a confirmed 404 — the URL genuinely does not exist (deleted tweet, removed video, etc.).

```json
{
  "url": "https://x.com/user/status/123",
  "raw_url": "https://x.com/user/status/123",
  "status": "error",
  "provider": "twitter",
  "error": "Not found (404)",
  "html": null
}
```

```json
{
  "url": "https://www.youtube.com/watch?v=invalid",
  "raw_url": "https://www.youtube.com/watch?v=invalid",
  "status": "error",
  "provider": "youtube",
  "error": "Not found (404)",
  "html": null
}
```

**How to distinguish error types:**
- `status: "error"` + `provider: null` → all providers failed (network/timeout/block)
- `status: "error"` + `provider: "twitter"` or `"youtube"` + `error: "Not found (404)"` → confirmed 404, the content does not exist
- `status: "error"` + `error` starts with `"Overall fetch timeout"` → request timed out

### `GET /api/v1/cache`

Return cache statistics: number of entries, total size, and per-entry details.

**Auth:** Bearer token in `Authorization` header.

**Response:**

```json
{
  "entry_count": 42,
  "total_size_bytes": 164392960,
  "total_size_mb": 156.78,
  "entries": [
    {
      "hash": "a1b2c3d4e5f6...",
      "versions": 3,
      "size_bytes": 524288,
      "size_kb": 512.0,
      "latest": "20260402T120000Z.json.gz",
      "latest_age_hours": 2.5
    }
  ]
}
```

### `DELETE /api/v1/cache`

Clear the entire response cache.

**Auth:** Bearer token in `Authorization` header.

**Response:**

```json
{
  "status": "ok",
  "entries_removed": 42,
  "size_freed_mb": 156.78
}
```

### `GET /api/v1/agents`

Returns the full content of this `AGENTS.md` file as plain text. Useful for AI agents that consume the scrapi API and need to understand its capabilities, response formats, and error handling at runtime.

**Auth:** Bearer token in `Authorization` header.

**Response:** Plain text (the raw markdown content of AGENTS.md).

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
  "data": "<base64>",
  "http": {
    "status": 200,
    "headers": {"content-type": "image/webp", "...": "..."},
    "redirect_history": null
  }
}
```

**Response (CSS/JS/SVG):**

```json
{
  "url": "https://example.com/style.css",
  "status": "success",
  "content_type": "text/css",
  "data": "<base64>",
  "http": {
    "status": 200,
    "headers": {"content-type": "text/css", "...": "..."},
    "redirect_history": null
  }
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

## Residential IP Proxy (SOCKS5 via SSH Reverse Tunnel)

Scrapi routes outbound requests through a MacBook Air's residential IP to avoid datacenter IP blocks. The proxy is optional — if `PROXY_URL` is unset, scrapi uses the server's direct connection.

**Architecture:**

```
scrapi (Swarm overlay) → socks-relay container (bridge+overlay) → host:1080 (SSH tunnel) → MacBook Air → internet
```

Three components:

1. **MacBook Air** runs `microsocks` (SOCKS5 proxy) on `127.0.0.1:1080`
2. **SSH reverse tunnel** from MacBook Air to vela binds `0.0.0.0:1080` on the server, forwarding to the MacBook's microsocks
3. **`socks-relay` container** on vela bridges Docker bridge network (can reach host:1080) to the `traefik-public` overlay (scrapi can reach it by name)

**Why the relay container?** Swarm overlay containers are isolated from the host network. The `socks-relay` container runs on the default bridge network (which can reach host ports via `172.17.0.1`) and is also connected to `traefik-public`, so scrapi reaches it at `socks-relay:1080`.

**Start/stop the tunnel (from MacBook Air):**

```bash
cd ~/scrapi
./scripts/tunnel.sh start    # Start microsocks + autossh reverse tunnel
./scripts/tunnel.sh stop     # Stop both
./scripts/tunnel.sh status   # Check if running
```

**Requirements on MacBook Air:** `brew install microsocks autossh`

**Manage the socks-relay container (on vela):**

```bash
# Create (one-time)
docker run -d --name socks-relay --restart always alpine/socat TCP-LISTEN:1080,fork,reuseaddr TCP:172.17.0.1:1080
docker network connect traefik-public socks-relay

# Check
docker logs socks-relay
docker exec socks-relay nc -w 3 172.17.0.1 1080  # should connect

# Restart
docker restart socks-relay

# Verify IP from server host
curl -x socks5://127.0.0.1:1080 -s https://api.ipify.org  # should show MacBook's residential IP
```

**UFW rule on vela:** Port 1080 must be open from the Docker bridge subnet:

```bash
sudo ufw allow from 172.17.0.0/16 to any port 1080 proto tcp comment "SOCKS relay from Docker bridge"
```

**What gets proxied:** Only the raw provider (Scrapling) and asset fetcher. API fetchers (Cloudflare, Firecrawl, Twitter, YouTube) are not proxied — they call external APIs, not target websites.

**`GatewayPorts`:** The server's `/etc/ssh/sshd_config` has `GatewayPorts clientspecified` to allow the tunnel to bind to `0.0.0.0` (required for Docker bridge access).

## Response Cache

Successful responses are cached to disk as gzip-compressed JSON files. This avoids re-fetching the same URL on repeated requests.

- **TTL:** 24 hours (configurable via `CACHE_TTL_HOURS`)
- **Versions kept:** 5 per URL (configurable via `CACHE_MAX_VERSIONS`), providing a history of past fetches
- **Max total size:** 20 GB (configurable via `CACHE_MAX_SIZE_GB`). When exceeded, caching is fully disabled (no reads, no writes) until cache is cleared
- **Cache key:** MD5 hash of the cleaned URL (after tracking param removal and query param sorting)
- **Storage:** gzip-compressed JSON files at `{CACHE_DIR}/{md5[:2]}/{md5}/{timestamp}.json.gz`
- **Atomic writes:** files are written to `.tmp` then renamed (POSIX atomic on same filesystem)
- **Docker dev:** bind-mount `./cache:/cache` (inspectable from host)
- **Docker prod:** named volume `scrapi_cache:/cache` (persistent, shared across replicas)

**Behavior:**
- By default, a cache hit within TTL is served immediately without contacting any provider
- `force_fetch=true` bypasses the cache read but still writes the fresh result to cache
- Only `status: "success"` results are cached. Errors are never cached.
- `DELETE /api/v1/cache` clears all cached data

## Environment Variables

- `SCRAPI_API_TOKEN` — required, the bearer token for API auth
- `SCRAPI_FETCH_TIMEOUT_MS` — optional, fetch timeout in ms (default: 30000)
- `PROVIDER_HARD_TIMEOUT_S` — optional, hard asyncio timeout per provider call in seconds (default: 45). Safety net that kills a hung provider.
- `FETCH_SINGLE_URL_TIMEOUT_S` — optional, hard timeout for the entire URL fetch (all providers + retries) in seconds (default: 120)
- `FIRECRAWL_API_KEY` — Firecrawl API key
- `CLOUDFLARE_API_KEY` — Cloudflare API key
- `CLOUDFLARE_ACCOUNT_ID` — Cloudflare account ID
- `PROXY_URL` — optional, SOCKS5 proxy URL (e.g. `socks5://socks-relay:1080`). Routes raw/asset fetches through the proxy
- `CACHE_DIR` — cache directory path (default: `/cache`)
- `CACHE_TTL_HOURS` — cache TTL in hours (default: 24)
- `CACHE_MAX_VERSIONS` — max versions to keep per URL (default: 5)
- `CACHE_MAX_SIZE_GB` — max total cache size in GB (default: 20). Cache disabled when exceeded
