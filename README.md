# Scrapi

Scrapi is a self-hosted scraping gateway. It fetches page content through a stealth Chromium ([CloakBrowser](https://github.com/CloakHQ/CloakBrowser)) with an optional [Firecrawl](https://firecrawl.dev) fallback, and also handles asset downloads, PDF/PNG exports, and stateless browser actions — over a small HTTP API or directly from the command line.

- **Providers**: `cloak` (local stealth Chromium, no API key) → `firecrawl` (optional, needs `FIRECRAWL_API_KEY`). Twitter/X and YouTube URLs are served by dedicated keyless fetchers.
- **Output**: cleaned HTML + markdown + head metadata, with content validation so captcha/shell pages are rejected and the next provider is tried.
- **No proxy required**: everything runs direct out of the box. Add a proxy (e.g. a residential SOCKS5 exit) only if you need one.

## Quick start (HTTP API)

```sh
cp .env.example .env
uv pip install -r requirements-dev.txt
SCRAPI_API_TOKEN=dev-token-change-me uv run uvicorn app.main:app --reload --port 10700
```

```sh
curl -H "Authorization: Bearer dev-token-change-me" \
  "http://localhost:10700/api/v1/content?urls=https://example.com"
```

Full endpoint documentation is generated live from the running code:

```sh
curl -sS http://localhost:10700/api/v1/agent
```

## CLI (no server, no token)

The same pipeline is available as a CLI — useful for one-shot jobs, cron, or invoking from another container:

```sh
python -m app.cli content https://example.com --format markdown
python -m app.cli asset https://example.com/logo.png --max-width 800 -o logo.png
python -m app.cli export --url https://example.com -o page.pdf
python -m app.cli actions --request action.json
python -m app.cli status
python -m app.cli agent        # print the API docs offline
```

`SCRAPI_API_TOKEN` is only needed to serve HTTP; the CLI runs without it.

## Docker

```sh
docker build -t scrapi .
# server
docker run --rm -p 10700:10700 -e SCRAPI_API_TOKEN=change-me scrapi
# one-shot CLI, no server
docker run --rm scrapi python -m app.cli content https://example.com
# or inside a running container
docker exec <container> python -m app.cli content https://example.com
```

For local development there is a `docker-compose.dev.yml`.

## Configuration

All configuration is via environment variables — see `.env.example`. Highlights:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCRAPI_API_TOKEN` | — | Bearer token for the HTTP API (required to serve; not needed for the CLI) |
| `PROXY_URL` | empty (direct) | Optional proxy for browser fetches, e.g. `socks5://host:1080` |
| `FIRECRAWL_API_KEY` | empty (disabled) | Enables the `firecrawl` fallback provider |
| `BROWSER_MAX_CONCURRENT` | `2` | Cap on concurrent Chromium instances (~500 MB RAM each) |

### Proxy profiles

`PROXY_URL` is the default `current` profile; when it's unset, `current` behaves like `direct` (no proxy). Add extra server-side profiles with JSON:

```sh
SCRAPI_PROXY_PROFILES_JSON='{"residential_backup":"http://user:pass@proxy.example:1234"}'
```

Then select one per request: `/api/v1/content?urls=...&proxy_profile=residential_backup` (or `--proxy-profile` on the CLI). Built-in profiles: `current`, `direct`. Raw proxy URLs are never accepted in requests; credentials stay in environment variables.

## Development

```sh
uv run pytest
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
```

## License

MIT — see [LICENSE](LICENSE).
