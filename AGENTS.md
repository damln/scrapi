# scrapi

FastAPI scraping gateway with a CLI twin (`python -m app.cli`).

API docs are generated live from the running code:

```sh
curl -sS http://localhost:10700/api/v1/agent
```

Do not duplicate endpoint params, providers, request bodies, or examples here.

## Local

```sh
uv pip install -r requirements-dev.txt
SCRAPI_API_TOKEN=test-token uv run uvicorn app.main:app --reload --port 10700
uv run pytest
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
```

## Deploy

CI runs on every push/PR (`.github/workflows/ci.yml`). Production deploy
config is private and gitignored — see `deploy/README.md` (local only).
