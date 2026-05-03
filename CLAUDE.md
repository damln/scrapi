# Scrapi — internal / operational notes

This is the **internal** doc for scrapi: deployment, infra, secrets,
ops gotchas. It is NOT served publicly.

For the **public API surface** (endpoints, request/response shapes,
provider chain, env vars, etc.) see [`AGENTS.md`](./AGENTS.md). That
file is also served at `/api/AGENTS.md` and `/api/v1/agent` so AI
agents can self-discover the API at runtime.

This split exists because the previous AGENTS.md was a symlink to
CLAUDE.md, which leaked internal hostnames (vela, the MacBook Air),
SSH tunnel architecture, internal Docker container names, and the
deploy skill reference to anyone who hit the agent endpoint.

## Deployment

For production deployment to the server, use the `damian-server` skill (`/damian-server`). It covers the full Docker Swarm deploy flow, config resolution via `os.yml` + `os_config.yml`, and all common pitfalls.

## Residential IP Proxy (SOCKS5 via SSH Reverse Tunnel)

Scrapi routes outbound requests through a Macbook Air's residential IP to avoid datacenter IP blocks. The proxy is optional — if `PROXY_URL` is unset, scrapi uses the server's direct connection.

**Architecture:**

```
scrapi (Swarm overlay) → socks-relay container (bridge+overlay) → host:1080 (SSH tunnel) → Macbook Air → internet
```

Three components:

1. **Macbook Air** runs `microsocks` (SOCKS5 proxy) on `127.0.0.1:1080`
2. **SSH reverse tunnel** from Macbook Air to vela binds `0.0.0.0:1080` on the server, forwarding to the Macbook Air's microsocks
3. **`socks-relay` container** on vela bridges Docker bridge network (can reach host:1080) to the `traefik-public` overlay (scrapi can reach it by name)

**Why the relay container?** Swarm overlay containers are isolated from the host network. The `socks-relay` container runs on the default bridge network (which can reach host ports via `172.17.0.1`) and is also connected to `traefik-public`, so scrapi reaches it at `socks-relay:1080`.

**Start/stop the tunnel (from Macbook Air):**

```bash
cd ~/scrapi
./scripts/tunnel.sh start    # Start microsocks + autossh reverse tunnel
./scripts/tunnel.sh stop     # Stop both
./scripts/tunnel.sh status   # Check if running
```

**Requirements on Macbook Air:** `brew install microsocks autossh`

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
curl -x socks5://127.0.0.1:1080 -s https://api.ipify.org  # should show Macbook Air's residential IP
```

**UFW rule on vela:** Port 1080 must be open from the Docker bridge subnet:

```bash
sudo ufw allow from 172.17.0.0/16 to any port 1080 proto tcp comment "SOCKS relay from Docker bridge"
```

**What gets proxied:** The scrapling provider, the asset fetcher, and the Twitter fetcher. Cloudflare, Firecrawl and YouTube fetchers are not proxied — they call external APIs from datacenter-friendly endpoints. Twitter is proxied because `api.fxtwitter.com` is behind Cloudflare and has 403'd vela's datacenter IP / httpx UA combo in the past; routing through the Macbook Air's residential IP plus a desktop-browser UA keeps it reliable.

**`GatewayPorts`:** The server's `/etc/ssh/sshd_config` has `GatewayPorts clientspecified` to allow the tunnel to bind to `0.0.0.0` (required for Docker bridge access).

## When to update this file vs AGENTS.md

- **AGENTS.md** — anything an external API consumer needs to know: endpoints, params, response shapes, provider behavior, env vars by name.
- **CLAUDE.md** (this file) — anything tied to *our* infra: vela, Macbook Air, deploy skill, internal hostnames, SSH tunnel, UFW rules. Things that would leak topology if a stranger read them.

If you add an env var, public field, or endpoint, update **AGENTS.md**.
If you change deploy or proxy infra, update **CLAUDE.md**.
