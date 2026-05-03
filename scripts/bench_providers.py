#!/usr/bin/env python3
"""Compare scrapi providers (obscura vs scrapling, by default) on a set of URLs.

Usage
-----
    # Defaults: localhost:10700, dev token, the URL list below.
    python scripts/bench_providers.py

    # Different host / token:
    SCRAPI_BASE=https://scrapi.damln.com SCRAPI_TOKEN=$PROD_TOKEN \\
        python scripts/bench_providers.py

    # Custom URLs:
    python scripts/bench_providers.py \\
        https://example.com \\
        https://news.ycombinator.com

    # Different providers to compare:
    PROVIDERS=obscura,scrapling,cloudflare python scripts/bench_providers.py

What it measures
----------------
Per (URL, provider) pair: HTTP latency end-to-end (requests perspective),
returned `provider` field (so we can see when a chain falls through), HTML
length, and a one-line success/failure verdict. Each request runs twice
back-to-back per provider — the first run fights cold scrapling/Camoufox
spawn (~5-10 s) which would otherwise distort the comparison; we report
both numbers so you can see warm-vs-cold.

Cache is not used (no `cache=...` query param), so every call really
hits the provider.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request


SCRAPI_BASE = os.environ.get("SCRAPI_BASE", "http://127.0.0.1:10700").rstrip("/")
SCRAPI_TOKEN = os.environ.get("SCRAPI_TOKEN", "dev-token-change-me")
PROVIDERS = [p.strip() for p in os.environ.get("PROVIDERS", "obscura,scrapling").split(",") if p.strip()]
RUNS_PER_PROVIDER = int(os.environ.get("RUNS", "2"))
REQUEST_TIMEOUT_S = int(os.environ.get("REQUEST_TIMEOUT_S", "180"))


DEFAULT_URLS = [
    # Baseline — static page, no JS, no anti-bot.
    "https://example.com",
    # Medium — JS-heavy SPA, no anti-bot.
    "https://news.ycombinator.com",
    # Adevinta WAF (the original target obscura was added for).
    "https://www.coches.net/segunda-mano/?MinPrice=6000&MaxPrice=13000&st=2",
    # Adevinta + DataDome — harder real estate.
    "https://www.idealista.com/venta-viviendas/madrid-madrid/",
    # DataDome — French classifieds, traditionally hostile to scrapers.
    "https://www.leboncoin.fr/recherche?category=10&locations=Paris",
]


def fetch(url: str, provider: str) -> dict:
    qs = urllib.parse.urlencode({"urls": url, "provider_order": provider})
    full = f"{SCRAPI_BASE}/api/v1/content?{qs}"
    req = urllib.request.Request(full, headers={"Authorization": f"Bearer {SCRAPI_TOKEN}"})

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.monotonic() - t0
    except Exception as exc:
        return {
            "elapsed_s": time.monotonic() - t0,
            "ok": False,
            "provider_returned": None,
            "html_len": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if "results" not in body or not body["results"]:
        return {
            "elapsed_s": elapsed,
            "ok": False,
            "provider_returned": None,
            "html_len": 0,
            "error": body.get("error") or "no results in response",
        }

    r = body["results"][0]
    html_len = len(r.get("html") or "")
    http = r.get("http") or {}
    status = http.get("status")
    success = r.get("status") == "success"
    # Blocked: provider returned 200 in scrapi but upstream HTTP status
    # (when known) says 4xx/5xx; or we have a status but the body is
    # tiny (<2 KB) — sometimes WAFs return 200 on the challenge page.
    # We DON'T speculate on size when http_status is unavailable
    # (cloudflare/firecrawl don't surface it), to avoid false-positiving
    # legitimately small static pages like example.com.
    blocked_by_status = isinstance(status, int) and status >= 400
    likely_blocked_by_size = (
        success
        and 0 < html_len < 2_000
        and isinstance(status, int)
        and status not in (200, 204)
    )
    return {
        "elapsed_s": elapsed,
        "ok": success,
        "provider_returned": r.get("provider"),
        "html_len": html_len,
        "blocked": blocked_by_status or likely_blocked_by_size,
        "egress_ip": r.get("egress_ip"),
        "http_status": status,
        "http_source": http.get("source"),
        "server": (http.get("headers") or {}).get("server"),
        "error": r.get("error"),
    }


def main(urls: list[str]) -> int:
    print(f"# scrapi provider benchmark")
    print(f"# base    : {SCRAPI_BASE}")
    print(f"# providers: {','.join(PROVIDERS)}  ({RUNS_PER_PROVIDER} runs each)")
    print(f"# urls    : {len(urls)}")
    print()

    fmt = "{:<55} {:<12} {:<6} {:>9} {:>10} {:<14} {:>5} {:<16} {:<16} {}"
    print(fmt.format("url", "provider req", "run", "elapsed_s", "html_len", "served_by", "http", "egress_ip", "server", "verdict"))
    print(fmt.format("-" * 55, "-" * 12, "-" * 6, "-" * 9, "-" * 10, "-" * 14, "-" * 5, "-" * 16, "-" * 16, "-" * 30))

    summary: dict[tuple[str, str], list[dict]] = {}

    for url in urls:
        url_short = url[:55]
        for provider in PROVIDERS:
            for i in range(1, RUNS_PER_PROVIDER + 1):
                r = fetch(url, provider)
                key = (url, provider)
                summary.setdefault(key, []).append(r)
                served = r["provider_returned"] or "-"
                if not r["ok"]:
                    verdict = (r["error"] or "fail")[:55]
                elif r["blocked"]:
                    if isinstance(r["http_status"], int) and r["http_status"] >= 400:
                        verdict = f"BLOCKED (http {r['http_status']})"
                    else:
                        verdict = f"BLOCKED (suspicious size {r['html_len']}B)"
                elif served != provider:
                    verdict = f"ok (FELL THROUGH: requested {provider}, served by {served})"
                else:
                    verdict = "ok"
                print(fmt.format(
                    url_short,
                    provider,
                    f"{i}/{RUNS_PER_PROVIDER}",
                    f"{r['elapsed_s']:.2f}",
                    r["html_len"],
                    served,
                    str(r["http_status"] or "-"),
                    (r["egress_ip"] or "-")[:16],
                    (r["server"] or "-")[:16],
                    verdict,
                ))

    # ------------------------------------------------------------------
    # Per-(url, provider) summary
    # ------------------------------------------------------------------
    print()
    print("# Per-(url, provider) summary — median elapsed across runs")
    print()
    sfmt = "{:<55} {:<12} {:>9} {:>9} {:>5} {}"
    print(sfmt.format("url", "provider", "median_s", "min_s", "ok/n", "served_by"))
    print(sfmt.format("-" * 55, "-" * 12, "-" * 9, "-" * 9, "-" * 5, "-" * 30))
    for (url, provider), runs in summary.items():
        elapsed = [r["elapsed_s"] for r in runs]
        ok_n = sum(1 for r in runs if r["ok"])
        served = sorted({r["provider_returned"] for r in runs if r["provider_returned"]})
        print(sfmt.format(
            url[:55],
            provider,
            f"{statistics.median(elapsed):.2f}",
            f"{min(elapsed):.2f}",
            f"{ok_n}/{len(runs)}",
            ",".join(served) or "-",
        ))

    # ------------------------------------------------------------------
    # Per-URL head-to-head: obscura vs scrapling speedup
    # Only counts runs that were both ok AND not blocked — comparing
    # "time to receive a block page" between providers is noise.
    # ------------------------------------------------------------------
    if "obscura" in PROVIDERS and "scrapling" in PROVIDERS:
        print()
        print("# Head-to-head — obscura speedup vs scrapling (median; both must be ok and not blocked)")
        print()
        hfmt = "{:<55} {:>12} {:>12} {:>10}"
        print(hfmt.format("url", "obscura_med", "scrapling_med", "speedup"))
        print(hfmt.format("-" * 55, "-" * 12, "-" * 12, "-" * 10))
        for url in urls:
            o = summary.get((url, "obscura"), [])
            s = summary.get((url, "scrapling"), [])
            if not o or not s:
                continue
            real_o = [r["elapsed_s"] for r in o if r["ok"] and not r["blocked"]]
            real_s = [r["elapsed_s"] for r in s if r["ok"] and not r["blocked"]]
            if not real_o or not real_s:
                why = "obscura blocked" if not real_o else "scrapling blocked" if not real_s else "n/a"
                print(hfmt.format(url[:55], "-" if not real_o else "ok", "-" if not real_s else "ok", why))
                continue
            mo = statistics.median(real_o)
            ms = statistics.median(real_s)
            print(hfmt.format(url[:55], f"{mo:.2f}s", f"{ms:.2f}s", f"{ms / mo:.2f}x"))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or DEFAULT_URLS))
