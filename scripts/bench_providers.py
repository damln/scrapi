#!/usr/bin/env python3
"""Compare scrapi providers on a set of URLs.

Usage
-----
    SCRAPI_BASE_URL=http://localhost:10700 SCRAPI_TOKEN=dev-token-change-me \\
        python scripts/bench_providers.py

    # Custom URLs:
    python scripts/bench_providers.py \\
        https://example.com \\
        https://news.ycombinator.com

    # Different providers to compare:
    PROVIDERS=cloak,firecrawl python scripts/bench_providers.py

What it measures
----------------
Per (URL, provider) pair: HTTP latency end-to-end (requests perspective),
returned `provider` field (so we can see when a chain falls through), HTML
length, and a one-line success/failure verdict. One request per (URL,
provider) by default — set RUNS=N to repeat for warm-vs-cold comparison.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request


_BLOCK_SENTINEL = re.compile(
    r"access denied"
    r"|just a moment\.\.\."
    r"|please enable js"
    r"|we just need to make sure you'?re not a robot"
    r"|recaptcha requires verification"
    r"|px-captcha"
    r"|datadome"
    r"|are you a human",
    re.I,
)


SCRAPI_BASE = os.environ.get("SCRAPI_BASE_URL", "http://localhost:10700").rstrip("/")
SCRAPI_TOKEN = os.environ.get("SCRAPI_TOKEN")
if not SCRAPI_TOKEN:
    sys.exit("SCRAPI_TOKEN env var required.")
PROVIDERS = [
    p.strip()
    for p in os.environ.get("PROVIDERS", "cloak,firecrawl").split(",")
    if p.strip()
]
RUNS_PER_PROVIDER = int(os.environ.get("RUNS", "1"))
REQUEST_TIMEOUT_S = int(os.environ.get("REQUEST_TIMEOUT_S", "180"))
CSV_PATH = os.environ.get("CSV_PATH") or str(
    pathlib.Path(__file__).resolve().parent.parent
    / "_tmp"
    / f"bench_providers_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
)


DEFAULT_URLS = [
    # Static, no JS, no anti-bot.
    "https://example.com",
    "https://en.wikipedia.org/wiki/Web_scraping",
    # JS-heavy SPA, no anti-bot.
    "https://news.ycombinator.com",
    "https://stackoverflow.com/questions",
    # Adevinta WAF.
    "https://www.coches.net/segunda-mano/?MinPrice=6000&MaxPrice=13000&st=2",
    "https://www.idealista.com/venta-viviendas/madrid-madrid/",
    # DataDome.
    "https://www.leboncoin.fr/recherche?category=10&locations=Paris",
    "https://www.glassdoor.com/Job/spain-jobs-SRCH_IL.0,5_IN219.htm",
    # Akamai.
    "https://www.kayak.com/flights/MAD-PAR/2026-06-15",
    # PerimeterX / HUMAN.
    "https://www.zillow.com/madrid-spain/",
    # Amazon's in-house bot detection.
    "https://www.amazon.com/dp/B08N5WRWNW",
    # Cloudflare bot management + custom.
    "https://www.indeed.com/jobs?q=software+engineer&l=Madrid",
]


def _result(
    *,
    elapsed_s: float,
    ok: bool,
    provider_returned: str | None = None,
    html_len: int = 0,
    blocked: bool = False,
    http_status: int | None = None,
    error: str | None = None,
) -> dict:
    return {
        "elapsed_s": elapsed_s,
        "ok": ok,
        "provider_returned": provider_returned,
        "html_len": html_len,
        "blocked": blocked,
        "http_status": http_status,
        "error": error,
    }


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
        return _result(
            elapsed_s=time.monotonic() - t0,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    if "results" not in body or not body["results"]:
        return _result(
            elapsed_s=elapsed,
            ok=False,
            error=body.get("error") or "no results in response",
        )

    r = body["results"][0]
    html = r.get("html") or ""
    html_len = len(html)
    http = r.get("http") or {}
    status = None if http.get("source") == "sibling-httpx" else http.get("status")
    success = r.get("status") == "success"
    blocked_by_status = isinstance(status, int) and status >= 400
    blocked_by_sentinel = success and bool(_BLOCK_SENTINEL.search(html[:50_000]))
    return _result(
        elapsed_s=elapsed,
        ok=success,
        provider_returned=r.get("provider"),
        html_len=html_len,
        blocked=blocked_by_status or blocked_by_sentinel,
        http_status=status,
        error=r.get("error"),
    )


def main(urls: list[str]) -> int:
    print(f"# scrapi provider benchmark")
    print(f"# base    : {SCRAPI_BASE}")
    print(f"# providers: {','.join(PROVIDERS)}  ({RUNS_PER_PROVIDER} runs each)")
    print(f"# urls    : {len(urls)}")
    print(f"# csv     : {CSV_PATH}")
    print()

    pathlib.Path(CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
    csv_file = open(CSV_PATH, "w", newline="", encoding="utf-8")
    csv_w = csv.writer(csv_file)
    csv_w.writerow([
        "url", "provider_requested", "run", "runs_total",
        "elapsed_s", "ok", "blocked", "provider_returned",
        "http_status", "html_len", "error", "verdict",
    ])

    fmt = "{:<55} {:<12} {:<6} {:>9} {:>10} {:<14} {:>5} {}"
    print(fmt.format("url", "provider req", "run", "elapsed_s", "html_len", "served_by", "http", "verdict"))
    print(fmt.format("-" * 55, "-" * 12, "-" * 6, "-" * 9, "-" * 10, "-" * 14, "-" * 5, "-" * 30))

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
                        verdict = f"BLOCKED (sentinel match, {r['html_len']}B)"
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
                    verdict,
                ), flush=True)
                csv_w.writerow([
                    url, provider, i, RUNS_PER_PROVIDER,
                    f"{r['elapsed_s']:.3f}", r["ok"], r["blocked"], served,
                    r["http_status"] if r["http_status"] is not None else "",
                    r["html_len"], r["error"] or "", verdict,
                ])
                csv_file.flush()
    csv_file.close()

    # Per-(url, provider) summary
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

    # Per-URL provider verdict matrix: at-a-glance "who got real content".
    # Cell shows median html_len when the run was ok-and-not-blocked, or
    # `BLOCK` / `FAIL` otherwise. Biggest cell wins.
    print()
    print("# Verdict matrix — median html_len when ok, BLOCK / FAIL otherwise")
    print()
    cell_w = 12
    mfmt = "{:<55} " + " ".join(["{:>" + str(cell_w) + "}"] * len(PROVIDERS))
    print(mfmt.format("url", *PROVIDERS))
    print(mfmt.format("-" * 55, *(["-" * cell_w] * len(PROVIDERS))))
    for url in urls:
        cells = []
        for provider in PROVIDERS:
            runs = summary.get((url, provider), [])
            if not runs:
                cells.append("-")
                continue
            clean = [r for r in runs if r["ok"] and not r["blocked"]]
            if clean:
                cells.append(f"{int(statistics.median([r['html_len'] for r in clean])):>10}B")
            elif any(r["blocked"] for r in runs):
                cells.append("BLOCK")
            else:
                cells.append("FAIL")
        print(mfmt.format(url[:55], *cells))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or DEFAULT_URLS))
