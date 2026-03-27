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

## Environment Variables

- `SCRAPI_API_TOKEN` — required, the bearer token for API auth
- `SCRAPI_FETCH_TIMEOUT_MS` — optional, fetch timeout in ms (default: 30000)
