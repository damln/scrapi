"""Obscura provider — calls the Obscura headless-browser CLI binary.

Obscura is a single-binary Rust headless browser
(https://github.com/h4ckf0r0day/obscura). It runs JavaScript via V8 with
built-in anti-detection (`--stealth`) at a fraction of the memory and
startup cost of Chrome. We spawn it as a subprocess and read rendered
HTML from stdout — no Python wrapper, no Playwright/Puppeteer client.

Why a subprocess (not a CDP client to `obscura serve`):
- Each fetch gets a clean process, so a crash in one page can't poison
  the next.
- Cancellation is reliable: we SIGKILL the process group, exactly like
  the scrapling worker.

Failure modes returned to the caller as exceptions:
- Binary missing -> FileNotFoundError (re-raised, caller logs/falls through)
- Non-zero exit  -> RuntimeError with stderr tail
- Empty stdout   -> RuntimeError (treated as a fetch failure, not a hang)
"""

import asyncio
import logging
import os
import signal

from app.config import OBSCURA_BIN

logger = logging.getLogger(__name__)


# Map scrapi's public `wait_until` values to obscura's CLI vocabulary.
# scrapi only exposes "networkidle" today; obscura calls the equivalent
# "networkidle0" (zero in-flight requests). Anything else falls back to
# obscura's default ("load").
_WAIT_UNTIL_MAP = {
    "networkidle": "networkidle0",
}


def _killpg(pid: int) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning("killpg(%s) denied: %s", pgid, exc)


async def fetch_with_obscura(
    url: str,
    wait_until: str | None = None,
    wait_for_selector: str | None = None,
) -> tuple[str, dict]:
    """Fetch a URL with the Obscura CLI in stealth mode. Returns (html, http_metadata).

    `http_metadata` is always an empty dict — Obscura's `fetch` subcommand
    does not surface HTTP status/headers/redirects on stdout. Callers that
    need that info should fall through to the scrapling provider.
    """
    cmd = [OBSCURA_BIN, "fetch", url, "--dump", "html", "--stealth", "--quiet"]
    if wait_until:
        mapped = _WAIT_UNTIL_MAP.get(wait_until, wait_until)
        cmd.extend(["--wait-until", mapped])
    if wait_for_selector:
        cmd.extend(["--selector", wait_for_selector])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        _killpg(proc.pid)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass
        raise

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"obscura exit {proc.returncode}: {err[:500]}")

    html = stdout.decode("utf-8", errors="replace")
    if not html.strip():
        raise RuntimeError("obscura returned empty stdout")

    return html, {}
