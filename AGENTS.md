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

- `GET /api/v1/content?urls=https://example.com&urls=https://other.com`
- Auth: Bearer token in `Authorization` header
- Returns full HTML with all relative links converted to absolute

## Test

Single URL:

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:8000/api/v1/content?urls=https://damln.com"

curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:8000/api/v1/content?urls=https://www.airbnb.com/rooms/1390463594335012333?check_in=2026-07-10&check_out=2026-07-12&photo_id=2198427852&source_impression_id=p3_1774637206_P3sg_i0zJQ6efoL-&previous_page_section_name=1000"

curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:8000/api/v1/content?urls=https://www.nytimes.com/spotlight/lifestyle"
```

Multiple URLs (repeat the `urls` param):

```bash
curl -H "Authorization: Bearer dev-token-change-me" "http://localhost:8000/api/v1/content?urls=https://damln.com&urls=https://example.com&urls=https://other.com"
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

## Ad/Tracker Blocking

Built-in via Scrapling's `disable_ads=True` parameter, which installs **uBlock Origin** as a Firefox addon in the Camoufox browser. This blocks ads, trackers, and analytics at the network level — no custom domain lists needed.

## Environment Variables

- `SCRAPI_API_TOKEN` — required, the bearer token for API auth
- `SCRAPI_FETCH_TIMEOUT_MS` — optional, fetch timeout in ms (default: 30000)
