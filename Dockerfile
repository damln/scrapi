FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

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
