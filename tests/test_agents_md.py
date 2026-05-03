"""Tests for the public AGENTS.md endpoints.

We have two paths that serve the same content:
- `/api/AGENTS.md` — agent-friendly canonical path
- `/api/v1/agent`  — legacy alias kept for backwards compatibility

Both must return the same body, no auth, plain text.

Plus: AGENTS.md must NOT contain content that should only live in CLAUDE.md
(deploy infra, internal hostnames, SSH tunnel architecture). The whole
point of the public/private split is that anonymous callers can hit the
endpoint without leaking topology.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = REPO_ROOT / "AGENTS.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


# ---------------------------------------------------------------------------
# Both endpoints serve the same content, no auth required
# ---------------------------------------------------------------------------


def test_agents_md_endpoint_returns_file_content(client):
    resp = client.get("/api/AGENTS.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == AGENTS_MD.read_text(encoding="utf-8")


def test_legacy_agent_endpoint_returns_same_content(client):
    a = client.get("/api/AGENTS.md")
    b = client.get("/api/v1/agent")
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.text == b.text


def test_agents_md_endpoint_requires_no_auth(client):
    # No Authorization header — must still succeed.
    resp = client.get("/api/AGENTS.md")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Public/private split: AGENTS.md must NOT carry internal topology
# ---------------------------------------------------------------------------


# Markers that belong to CLAUDE.md only — leaking any of these via the
# public endpoint would expose deploy infra to anonymous callers. Add
# new markers here if you ever land another internal-only doc section.
INTERNAL_ONLY_MARKERS = [
    "vela",                      # internal Docker Swarm hostname
    "Macbook Air",               # owner of the residential IP proxy
    "damian-server",             # internal deploy skill name
    "GatewayPorts clientspecified",  # SSH config detail
    "socks-relay",               # internal Docker container name
    "172.17.0.1",                # internal Docker bridge IP
    "172.17.0.0/16",             # internal Docker bridge subnet
    "microsocks",                # SOCKS5 daemon name (internal infra)
    "autossh",                   # SSH tunnel daemon (internal infra)
    "api.fxtwitter.com",         # internal Twitter fetch implementation
]


@pytest.mark.parametrize("marker", INTERNAL_ONLY_MARKERS)
def test_public_agents_md_does_not_leak_internal_marker(marker):
    body = AGENTS_MD.read_text(encoding="utf-8")
    assert marker not in body, (
        f"AGENTS.md contains internal-only marker {marker!r}. "
        f"Move that section into CLAUDE.md — AGENTS.md is served publicly."
    )


def test_internal_markers_actually_live_in_claude_md():
    # Sanity check on the test itself: every marker we guard against in
    # AGENTS.md should genuinely exist in CLAUDE.md, otherwise the
    # marker is stale and the guard is meaningless.
    body = CLAUDE_MD.read_text(encoding="utf-8")
    missing = [m for m in INTERNAL_ONLY_MARKERS if m not in body]
    assert not missing, (
        f"INTERNAL_ONLY_MARKERS contains markers not in CLAUDE.md: {missing}. "
        f"Either remove them from the test or move that content back into CLAUDE.md."
    )


def test_agents_md_is_a_real_file_not_a_symlink():
    # The original AGENTS.md was a symlink to CLAUDE.md, which is
    # exactly what caused the leak. Pin the file type so a future
    # `ln -sf CLAUDE.md AGENTS.md` regresses a test instead of prod.
    assert AGENTS_MD.exists()
    assert not AGENTS_MD.is_symlink(), (
        "AGENTS.md must be a real file, not a symlink to CLAUDE.md — "
        "the symlink form leaks internal infra to the public endpoint."
    )
