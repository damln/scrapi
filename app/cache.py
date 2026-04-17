import gzip
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import shutil

from app.config import CACHE_DIR, CACHE_MAX_SIZE_BYTES, CACHE_MAX_VERSIONS

logger = logging.getLogger(__name__)


def cache_size_bytes() -> int:
    """Return total size of all files in the cache directory in bytes."""
    root = Path(CACHE_DIR)
    if not root.exists():
        return 0
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def cache_info() -> dict:
    """Return cache statistics: entry count, total size, and per-entry details."""
    root = Path(CACHE_DIR)
    if not root.exists():
        return {"entry_count": 0, "total_size_bytes": 0, "total_size_mb": 0.0, "entries": []}

    entries = []
    total_size = 0

    for prefix_dir in sorted(root.iterdir()):
        if not prefix_dir.is_dir():
            continue
        for entry_dir in sorted(prefix_dir.iterdir()):
            if not entry_dir.is_dir():
                continue
            files = [f for f in entry_dir.iterdir() if f.is_file() and f.name.endswith(".json.gz")]
            if not files:
                continue
            entry_size = sum(f.stat().st_size for f in files)
            total_size += entry_size
            sorted_files = sorted(files, key=lambda f: f.name)
            latest = sorted_files[-1]
            ts = _parse_timestamp(latest.name)
            entries.append({
                "hash": entry_dir.name,
                "versions": len(files),
                "size_bytes": entry_size,
                "size_kb": round(entry_size / 1024, 2),
                "latest": latest.name,
                "latest_age_hours": round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1) if ts else None,
            })

    return {
        "entry_count": len(entries),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "entries": entries,
    }


def clear_cache() -> int:
    """Delete all cached files. Returns the number of files removed."""
    root = Path(CACHE_DIR)
    if not root.exists():
        return 0
    count = 0
    for child in list(root.iterdir()):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            count += 1
    logger.info("Cache cleared (%d top-level entries removed)", count)
    return count


def _cache_dir_for_url(cleaned_url: str) -> Path:
    """Return the directory path for a cleaned URL's cache entries."""
    md5 = hashlib.md5(cleaned_url.encode("utf-8")).hexdigest()
    return Path(CACHE_DIR) / md5[:2] / md5


def _timestamp_str() -> str:
    """Return current UTC timestamp as a filesystem-safe string."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_timestamp(filename: str) -> datetime | None:
    """Parse a UTC timestamp from a cache filename like '20260401T143022Z.json.gz'."""
    stem = filename.replace(".json.gz", "")
    try:
        return datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _list_versions(cache_dir: Path) -> list[Path]:
    """Return all .json.gz files in the cache dir, sorted oldest to newest."""
    if not cache_dir.exists():
        return []
    files = [f for f in cache_dir.iterdir() if f.name.endswith(".json.gz")]
    return sorted(files, key=lambda f: f.name)


def read_cache(cleaned_url: str, ttl_hours: float) -> dict | None:
    """Return the cached result for a cleaned URL if within the given TTL, else None."""
    if cache_size_bytes() >= CACHE_MAX_SIZE_BYTES:
        logger.warning("Cache at max size (%d GB limit) — bypassing read for %s", CACHE_MAX_SIZE_BYTES // (1024**3), cleaned_url)
        return None

    cache_dir = _cache_dir_for_url(cleaned_url)
    versions = _list_versions(cache_dir)
    if not versions:
        logger.debug("Cache miss (no versions): %s", cleaned_url)
        return None

    latest = versions[-1]
    ts = _parse_timestamp(latest.name)
    if ts is None:
        logger.debug("Cache miss (unparseable timestamp): %s", latest.name)
        return None

    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if age_hours > ttl_hours:
        logger.debug("Cache miss (expired, %.1fh old, ttl %.1fh): %s", age_hours, ttl_hours, cleaned_url)
        return None

    try:
        with gzip.open(latest, "rt", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("Cache hit (%.1fh old): %s", age_hours, cleaned_url)
        return data
    except Exception as exc:
        logger.warning("Cache read error for %s: %s — treating as miss", latest, exc)
        return None


def write_cache(cleaned_url: str, result: dict) -> None:
    """Write a successful result to cache atomically, then prune old versions."""
    if cache_size_bytes() >= CACHE_MAX_SIZE_BYTES:
        logger.warning("Cache at max size (%d GB limit) — skipping write for %s", CACHE_MAX_SIZE_BYTES // (1024**3), cleaned_url)
        return

    cache_dir = _cache_dir_for_url(cleaned_url)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create cache dir %s: %s", cache_dir, exc)
        return

    filename = _timestamp_str() + ".json.gz"
    final_path = cache_dir / filename
    tmp_path = cache_dir / (filename + ".tmp")

    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(result, f)
        os.rename(tmp_path, final_path)
        logger.debug("Cache written: %s", final_path)
    except Exception as exc:
        logger.error("Cache write error for %s: %s", cleaned_url, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return

    _prune_old_versions(cache_dir)


def _prune_old_versions(cache_dir: Path) -> None:
    """Delete oldest versions beyond CACHE_MAX_VERSIONS."""
    versions = _list_versions(cache_dir)
    excess = versions[: max(0, len(versions) - CACHE_MAX_VERSIONS)]
    for old_file in excess:
        try:
            old_file.unlink()
            logger.debug("Cache pruned: %s", old_file)
        except Exception as exc:
            logger.warning("Cache prune error for %s: %s", old_file, exc)
