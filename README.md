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
