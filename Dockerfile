# Single-stage scrapi runtime. CloakBrowser (Chromium with C++ stealth
# patches) is the single browser-based provider; firecrawl is the paid
# fallback. Earlier providers (obscura, cloudflare, scrapling) are
# documented in CLAUDE.md's "Removed providers" section.
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

# Ad/tracker host denylist for app.ad_blocker. Pulled at build time from
# StevenBlack/hosts at a pinned release tag and stripped to one host per
# line. ~80K entries. Re-pin manually when the upstream list ages out.
# This replaces the ~50-host hardcoded fallback list that shipped in
# the first cut of ad_blocker.py; the legacy list still loads if this
# file is missing (e.g. local dev with an outdated image).
ARG ADBLOCK_HOSTS_REF=3.16.81
RUN curl -sSLf "https://raw.githubusercontent.com/StevenBlack/hosts/${ADBLOCK_HOSTS_REF}/hosts" \
    | awk '/^0\.0\.0\.0/ {print $2}' \
    | grep -v '^0\.0\.0\.0$' \
    > /opt/adblock_hosts.txt && \
    wc -l /opt/adblock_hosts.txt

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt

# Install Chromium's system library dependencies (libglib, libnss,
# libatk, libcups, libxkbcommon, etc.). cloakbrowser ships its own
# Chromium binary but doesn't carry shared libs; Playwright (transitive
# dep of cloakbrowser) provides this convenience CLI that apt-installs
# the exact set Chromium needs. Previously this happened implicitly via
# `scrapling install`, removed when scrapling was retired.
RUN playwright install-deps chromium

# CloakBrowser's custom Chromium binary (~200 MB) auto-downloads on first
# `launch()` — we trigger that here so the first /content request after a
# cold deploy doesn't pay the download tax.
RUN python -c "from cloakbrowser import launch; b = launch(); b.close()"

COPY . .

RUN mkdir -p /tmp/.cache && chown -R 1002:1002 /tmp/.cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10700", "--workers", "2"]
