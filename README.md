# Scrapi

Self-hosted scraping, browser capture and export through an HTTP API or CLI.

## Start locally

From the repository root:

```sh
docker build -t scrapi .
docker run --rm -p 127.0.0.1:10700:10700 \
  -e SCRAPI_API_TOKEN=dev-token-change-me scrapi
```

In another terminal, fetch a page:

```sh
curl -H "Authorization: Bearer dev-token-change-me" \
  "http://localhost:10700/api/v1/content?urls=https://example.com"
```

For a one-shot CLI call without a server or token:

```sh
docker run --rm scrapi python -m app.cli content https://example.com
```

Use `python -m app.cli --help`, command-specific `--help`, or
`python -m app.cli agent` inside the image for the full interface.
The running service exposes the same [API guide](http://localhost:10700/api/v1/agent).

For ChatGPT image generation and polling, use the standard-library
[Python client](scripts/generate_images.py):

```sh
python3 scripts/generate_images.py "A watercolor fox" \
  --session /path/to/private/session.json --images ./references --output ./generated
```

An empty reference folder is accepted. Set `SCRAPI_BASE_URL` and
`SCRAPI_API_TOKEN` to call a remote instance. The live API guide owns the
request schema, limits and polling contract. Image jobs are held in memory,
so run a single API worker and expect jobs to disappear on restart.

The [local Compose stack](docker-compose.local.yml) mounts private session
files from `secrets/` (excluded from Git and image builds). Save your ChatGPT
cookie export as `secrets/chatgpt-session.json` to omit `--session`.
To use the home HTTP/HTTPS proxy in Docker, run its Cloudflare connector beside
Scrapi. Set `HOME_PROXY_ENV_FILE` to a private file containing
`TUNNEL_SERVICE_TOKEN_ID` and `TUNNEL_SERVICE_TOKEN_SECRET` for a token authorized
by the `Home proxy servers` Access policy:

```sh
HOME_PROXY_ENV_FILE="$HOME/.config/home-proxy/access.env" \
  docker compose -f docker-compose.local.yml \
  -f docker-compose.home-proxy.yml up -d --build
```

This routes Scrapi through `http://home-proxy:18888` to
`home-proxy.damianln.com`, then Tinyproxy on M1. No proxy port is published.
HTTPS destinations use CONNECT through this HTTP proxy. Cloudflare credentials
are provided only to the connector, not Scrapi or target websites.

For Scrapi running directly on a host with an existing connector:

```sh
PROXY_URL=http://127.0.0.1:18888 python -m app.cli content https://example.com
```

Use the generated CLI/API guide to select only Cloak and the current proxy
when home-IP routing is required; Firecrawl uses its own infrastructure.
The base local Compose file without the override still supports direct access
or a caller-supplied `PROXY_URL`. No tokens or SSH keys belong in the repository.

## Source map

- [app/main.py](app/main.py) and [app/cli.py](app/cli.py): entry points.
- [app/](app/): fetchers, browser operations, exports and validation.
- [app/config.py](app/config.py) and [.env.example](.env.example): configuration.
- [docker-compose.dev.yml](docker-compose.dev.yml): Diez development stack.
- [CI workflow](.github/workflows/ci.yml): lint and tests.

Set a private `SCRAPI_API_TOKEN` before exposing HTTP publicly. Direct local
requests may omit the bearer header; public-hostname requests require it,
including behind a Docker reverse proxy. Keep proxy credentials server-side;
requests select named profiles. See [app/auth.py](app/auth.py) and
[app/proxy_profiles.py](app/proxy_profiles.py) for the boundaries.

MIT - see [LICENSE](LICENSE).
