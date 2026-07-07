from app.agent_examples import EXAMPLE_PAGE_URL, response_examples


def test_agent_endpoint_is_public_live_markdown(client):
    resp = client.get("/api/v1/agent")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "source: live FastAPI/OpenAPI + Pydantic schemas generated at request time" in resp.text
    assert "GET /api/v1/content" in resp.text
    assert "POST /api/v1/export" in resp.text
    assert "POST /api/v1/actions" in resp.text
    assert "provider_order" in resp.text
    assert "proxy_profile" in resp.text
    assert "Providers now: cloak, firecrawl" in resp.text
    assert "x_post params" in resp.text
    assert "dry_run" in resp.text
    assert "reply_url" in resp.text
    assert "returns example:" in resp.text
    assert EXAMPLE_PAGE_URL in resp.text
    assert "Hello Scrapi" in resp.text
    assert "x-scrapi-final-url" in resp.text


def test_agent_endpoint_does_not_serve_internal_markdown(client):
    resp = client.get("/api/v1/agent")

    assert resp.status_code == 200
    assert "All operational endpoints use `Authorization: Bearer $SCRAPI_API_TOKEN`" not in resp.text
    assert "Returns this file as plain text" not in resp.text
    assert "AGENTS.md" not in resp.text


def test_agents_md_route_is_not_exposed(client):
    resp = client.get("/api/v1/agents.md")

    assert resp.status_code == 404


def test_agent_response_examples_are_code_owned():
    examples = response_examples()

    content = examples["GET /api/v1/content"]
    assert content["results"][0]["status"] == "success"
    assert content["results"][0]["provider"] == "cloak"
    assert "markdown" in content["results"][0]

    action = examples["POST /api/v1/actions"]
    assert action["status"] == "success"
    assert action["result"]["dry_run"] is True
