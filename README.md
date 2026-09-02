# Scrapi

Scrapi is a self-hosted scraping gateway. It fetches page content through a stealth Chromium ([CloakBrowser](https://github.com/CloakHQ/CloakBrowser)) with an optional [Firecrawl](https://firecrawl.dev) fallback, and also handles browser evidence capture, asset downloads, PDF/PNG exports, and stateless browser actions — over a small HTTP API or directly from the command line.

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

YouTube content responses include all available native-language transcript tracks, with English selected first when
available. The primary transcript is also included in the returned HTML and markdown with timestamps.

Capture one JPEG screenshot, or repeat `viewport` to receive a ZIP with several responsive sizes:

```sh
curl -sS -G http://localhost:10700/api/v1/screenshot \
  -H "Authorization: Bearer dev-token-change-me" \
  --data-urlencode "url=https://example.com" \
  --data-urlencode "viewport=mobile" \
  --data-urlencode "viewport=desktop" \
  --data-urlencode "quality=98" \
  --data-urlencode "full_page=true" \
  --data-urlencode "max_page_height=20000" \
  -o screenshots.zip
```

`viewport` accepts `mobile` (`390x844`), `desktop` (`1440x1000`), or a custom `WIDTHxHEIGHT`, and can be repeated up
to five times. `scroll_full=true` triggers lazy content before capture; `max_scroll_steps` bounds infinite scrolling.
Full-page JPEG height is independently capped by `max_page_height`.

Capture browser evidence as a portable ZIP:

```sh
curl -sS -X POST http://localhost:10700/api/v1/capture \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","scroll_full":true,"video":true,"resources":"assets"}' \
  -o scrapi-capture.zip
unzip scrapi-capture.zip -d capture
```

The archive contains `result.json` plus the requested screenshot, WebM, HAR, rendered HTML,
and bounded resource downloads. The capture endpoint uses the same CloakBrowser, cookie
dismissal, ad blocking, proxy profiles, retries, and hard process cleanup as the CLI.

The bearer header may be omitted for direct requests to `localhost`, loopback addresses,
`host.docker.internal`, or Docker's private `172.16.0.0/12` bridge range. Requests through a
public hostname still require authentication, including when a reverse proxy runs on a Docker network.

Full endpoint documentation is generated live from the running code:

```sh
curl -sS http://localhost:10700/api/v1/agent
```

## CLI (no server, no token)

The same pipeline is available as a CLI — useful for one-shot jobs, cron, or invoking from another container:

```sh
python -m app.cli --help       # agent-friendly CLI guide and examples
python -m app.cli content https://example.com --format markdown
python -m app.cli asset https://example.com/logo.png --max-width 800 -o logo.png
python -m app.cli export --url https://example.com -o page.pdf
python -m app.cli capture https://example.com -o _tmp/example --video --scroll-full --resources assets
python -m app.cli actions --request action.json
python -m app.cli status
python -m app.cli agent        # print the API docs offline
```

`SCRAPI_API_TOKEN` is only needed to serve HTTP; the CLI runs without it.

`capture` uses the same CloakBrowser, humanized input, proxy profiles, ad blocking, cookie dismissal, and killable subprocess model as the content provider. It can emit a full/viewport screenshot, WebM, HAR, rendered HTML, and bounded response-resource downloads. Run `python -m app.cli capture --help` for all controls.

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
| `SCRAPI_API_TOKEN` | — | Bearer token for non-local HTTP API calls (required to serve; not needed for local calls or the CLI) |
| `PROXY_URL` | empty (direct) | Optional proxy for browser fetches, e.g. `socks5://host:1080` |
| `FIRECRAWL_API_KEY` | empty (disabled) | Enables the `firecrawl` fallback provider |
| `BROWSER_MAX_CONCURRENT` | `2` | Per-container budget shared by content, capture, export, and actions. Content reuses this many persistent Chromium workers (~500 MB RAM each under load). |
| `BROWSER_MAX_REQUESTS_PER_WORKER` | `100` | Recycle a persistent content browser after this many pages to bound long-lived Chromium growth. |

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
