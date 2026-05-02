# ---------------------------------------------------------------------------
# Stage 1: build Obscura from source with `--features stealth`.
#
# Verified the prebuilt v0.1.1 release does NOT honor `--stealth`:
# fingerprints (UA, hardwareConcurrency, deviceMemory) are identical with
# and without the flag, and per-session randomization never fires. The
# `stealth` Cargo feature is what pulls in `wreq` (TLS fingerprint
# mimicking) and the per-session randomization paths in obscura-browser /
# obscura-net. Building from source is the only way to actually get them.
#
# `target/release/obscura` is statically linkable enough to run in
# `python:3.12-slim` (glibc only). We discard the entire Rust toolchain
# in stage 2 so the final image isn't 1.5 GB.
# ---------------------------------------------------------------------------
ARG OBSCURA_VERSION=v0.1.1

FROM rust:1.88-slim-bookworm AS obscura-builder
# cmake + clang/libclang-dev are required by `boring-sys2` (BoringSSL
# build + bindgen FFI), pulled in transitively by `wreq` when
# `--features stealth` is enabled.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates pkg-config build-essential perl python3 cmake clang libclang-dev && \
    rm -rf /var/lib/apt/lists/*
ARG OBSCURA_VERSION
RUN git clone --depth 1 --branch "${OBSCURA_VERSION}" \
      https://github.com/h4ckf0r0day/obscura.git /src
WORKDIR /src
# `--bin obscura` skips building the unused `obscura-worker` binary
# (the `serve --workers N` mode is not used by scrapi). Smoke test fails
# the build if the resulting binary won't run in the builder's glibc —
# proxy for "won't run in the runtime image" since both stages are
# Debian bookworm-derived slim images with the same glibc family.
RUN cargo build --release --features stealth --bin obscura && \
    /src/target/release/obscura --help > /dev/null

# ---------------------------------------------------------------------------
# Stage 2: scrapi runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

# Pull in the from-source obscura binary built in stage 1.
COPY --from=obscura-builder /src/target/release/obscura /usr/local/bin/obscura
RUN /usr/local/bin/obscura --help > /dev/null

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
