FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

# Obscura headless-browser CLI — first provider in the fallback chain.
# Pinned by tag (not "latest") so image rebuilds are reproducible; bump
# this ARG when we want a newer release. Static Rust binary, no runtime
# deps. `--help` smoke test fails the build if the binary doesn't run in
# this base image, instead of letting prod discover it at request time.
ARG OBSCURA_VERSION=v0.1.1
RUN curl -fsSL "https://github.com/h4ckf0r0day/obscura/releases/download/${OBSCURA_VERSION}/obscura-x86_64-linux.tar.gz" \
      -o /tmp/obscura.tar.gz && \
    tar -xzf /tmp/obscura.tar.gz -C /usr/local/bin obscura && \
    rm /tmp/obscura.tar.gz && \
    chmod +x /usr/local/bin/obscura && \
    /usr/local/bin/obscura --help > /dev/null

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Authenticate api.github.com calls during `scrapling install` so camoufox's
# GeoLite mmdb fetch isn't 403'd by the shared-runner-IP unauth rate limit
# (60/hr -> 5000/hr). Token comes from the deploy-workflows build secret;
# requests honors ~/.netrc automatically. Netrc is removed in the same layer.
RUN --mount=type=secret,id=gh_token \
    if [ -s /run/secrets/gh_token ]; then \
      printf "machine api.github.com\n  login x-access-token\n  password %s\n" "$(cat /run/secrets/gh_token)" > /root/.netrc && \
      chmod 600 /root/.netrc; \
    fi && \
    scrapling install && \
    rm -f /root/.netrc

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10700", "--workers", "2"]
