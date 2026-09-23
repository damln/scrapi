FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

# Ad/tracker host denylist for app.ad_blocker, pulled from a pinned
# StevenBlack/hosts release. Re-pin manually when the upstream list ages out.
ARG ADBLOCK_HOSTS_REF=3.16.81
RUN curl -sSLf "https://raw.githubusercontent.com/StevenBlack/hosts/${ADBLOCK_HOSTS_REF}/hosts" \
    | awk '/^0\.0\.0\.0/ {print $2}' \
    | grep -v '^0\.0\.0\.0$' \
    > /opt/adblock_hosts.txt && \
    wc -l /opt/adblock_hosts.txt

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt

# cloakbrowser ships its own Chromium binary but not its shared libraries.
RUN playwright install-deps chromium

# Playwright uses its matching ffmpeg build for browser-context WebM video.
# Install it at build time so CLI captures never download tooling at runtime.
RUN playwright install ffmpeg

# CloakBrowser's custom Chromium binary (~200 MB) auto-downloads on first
# `launch()` — we trigger that here so the first /content request after a
# cold deploy doesn't pay the download tax.
RUN python -c "from cloakbrowser import launch; b = launch(); b.close()"

COPY . .

RUN mkdir -p /tmp/.cache && chown -R 1002:1002 /tmp/.cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10700"]
