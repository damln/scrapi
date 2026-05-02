import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("SCRAPI_API_TOKEN", "test-token")

SUCCESS_RESULT = {
    "url": "https://example.com",
    "raw_url": "https://example.com",
    "status": "success",
    "provider": "scrapling",
    "html": "<html><body><p>Hello</p></body></html>",
    "markdown": "Hello",
}

ERROR_RESULT = {
    "url": "https://example.com",
    "raw_url": "https://example.com",
    "status": "error",
    "provider": None,
    "error": "All providers failed",
    "html": None,
}


def _write_version(cache_dir: Path, ts_str: str, data: dict) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{ts_str}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# _cache_dir_for_url
# ---------------------------------------------------------------------------


def test_cache_dir_is_deterministic(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url

        d1 = _cache_dir_for_url("https://example.com")
        d2 = _cache_dir_for_url("https://example.com")
    assert d1 == d2


def test_cache_dir_uses_two_char_prefix(tmp_path):
    url = "https://example.com"
    md5 = hashlib.md5(url.encode()).hexdigest()
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url

        d = _cache_dir_for_url(url)
    assert d.parts[-2] == md5[:2]
    assert d.parts[-1] == md5


def test_different_urls_have_different_dirs(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url

        d1 = _cache_dir_for_url("https://example.com")
        d2 = _cache_dir_for_url("https://other.com")
    assert d1 != d2


# ---------------------------------------------------------------------------
# read_cache — miss
# ---------------------------------------------------------------------------


def test_read_cache_miss_no_dir(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import read_cache

        assert read_cache("https://example.com", 24) is None


def test_read_cache_miss_empty_dir(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, read_cache

        _cache_dir_for_url("https://example.com").mkdir(parents=True)
        assert read_cache("https://example.com", 24) is None


def test_read_cache_miss_expired(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, read_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=73)).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, old_ts, SUCCESS_RESULT)
        assert read_cache(url, 72) is None


def test_read_cache_corrupted_file_is_miss(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, read_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        cache_dir.mkdir(parents=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bad_file = cache_dir / f"{ts}.json.gz"
        bad_file.write_bytes(b"not valid gzip data")
        assert read_cache(url, 24) is None


# ---------------------------------------------------------------------------
# read_cache — hit
# ---------------------------------------------------------------------------


def test_read_cache_hit_fresh(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, read_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        fresh_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, fresh_ts, SUCCESS_RESULT)
        result = read_cache(url, 72)
    assert result is not None
    assert result["status"] == "success"
    assert result["html"] == SUCCESS_RESULT["html"]


def test_read_cache_returns_latest_version(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, read_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, old_ts, {**SUCCESS_RESULT, "html": "old"})
        new_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, new_ts, {**SUCCESS_RESULT, "html": "new"})
        result = read_cache(url, 24)
    assert result["html"] == "new"


# ---------------------------------------------------------------------------
# write_cache
# ---------------------------------------------------------------------------


def test_write_cache_creates_file(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, write_cache

        url = "https://example.com"
        write_cache(url, SUCCESS_RESULT)
        cache_dir = _cache_dir_for_url(url)
        files = list(cache_dir.glob("*.json.gz"))
    assert len(files) == 1


def test_write_cache_file_is_valid_gzip_json(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, write_cache

        url = "https://example.com"
        write_cache(url, SUCCESS_RESULT)
        cache_dir = _cache_dir_for_url(url)
        f = next(cache_dir.glob("*.json.gz"))
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    assert data["status"] == "success"
    assert data["html"] == SUCCESS_RESULT["html"]


def test_write_cache_no_tmp_file_left(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        cache_dir = _cache_dir_for_url("https://example.com")
        assert len(list(cache_dir.glob("*.tmp"))) == 0


# ---------------------------------------------------------------------------
# Version pruning
# ---------------------------------------------------------------------------


def test_write_cache_prunes_old_versions(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)), patch("app.cache.CACHE_MAX_VERSIONS", 3):
        from app.cache import _cache_dir_for_url, write_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        for i in range(3):
            ts = (datetime.now(timezone.utc) - timedelta(hours=10 - i)).strftime("%Y%m%dT%H%M%SZ")
            _write_version(cache_dir, ts, SUCCESS_RESULT)
        write_cache(url, SUCCESS_RESULT)
        files = list(cache_dir.glob("*.json.gz"))
    assert len(files) == 3


def test_write_cache_keeps_newest_versions(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)), patch("app.cache.CACHE_MAX_VERSIONS", 2):
        from app.cache import _cache_dir_for_url, write_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        old1_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y%m%dT%H%M%SZ")
        old2_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, old1_ts, {**SUCCESS_RESULT, "html": "oldest"})
        _write_version(cache_dir, old2_ts, {**SUCCESS_RESULT, "html": "middle"})
        write_cache(url, {**SUCCESS_RESULT, "html": "newest"})
        files = sorted(cache_dir.glob("*.json.gz"), key=lambda f: f.name)
    assert len(files) == 2
    contents = []
    for f in files:
        with gzip.open(f, "rt") as fh:
            contents.append(json.load(fh)["html"])
    assert "oldest" not in contents
    assert "newest" in contents


# ---------------------------------------------------------------------------
# Max size guard
# ---------------------------------------------------------------------------


def test_write_cache_skipped_when_max_size_exceeded(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)), patch("app.cache.CACHE_MAX_SIZE_BYTES", 1):
        from app.cache import _cache_dir_for_url, write_cache

        # Write one file manually to push size above 1 byte
        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, ts, SUCCESS_RESULT)

        # This write should be skipped
        write_cache("https://other.com", SUCCESS_RESULT)
        from app.cache import _cache_dir_for_url as cdf

        other_dir = cdf("https://other.com")
        assert not other_dir.exists()


def test_read_cache_bypassed_when_max_size_exceeded(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)), patch("app.cache.CACHE_MAX_SIZE_BYTES", 1):
        from app.cache import _cache_dir_for_url, read_cache

        url = "https://example.com"
        cache_dir = _cache_dir_for_url(url)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _write_version(cache_dir, ts, SUCCESS_RESULT)

        # Should return None despite valid cache, because size exceeds limit
        assert read_cache(url, 24) is None


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


def test_clear_cache_removes_all_entries(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import _cache_dir_for_url, clear_cache, write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        write_cache("https://other.com", SUCCESS_RESULT)
        assert _cache_dir_for_url("https://example.com").exists()

        count = clear_cache()
        assert count > 0
        # No subdirectories should remain
        remaining = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(remaining) == 0


def test_clear_cache_empty_dir(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import clear_cache

        assert clear_cache() == 0


def test_clear_cache_nonexistent_dir():
    with patch("app.cache.CACHE_DIR", "/nonexistent/path/that/does/not/exist"):
        from app.cache import clear_cache

        assert clear_cache() == 0


# ---------------------------------------------------------------------------
# cache_size_bytes
# ---------------------------------------------------------------------------


def test_cache_size_bytes_empty(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import cache_size_bytes

        assert cache_size_bytes() == 0


def test_cache_size_bytes_with_files(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import cache_size_bytes, write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        assert cache_size_bytes() > 0


# ---------------------------------------------------------------------------
# DELETE /api/v1/cache endpoint
# ---------------------------------------------------------------------------

from tests.conftest import AUTH_HEADER


def test_cache_info_empty(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import cache_info

        info = cache_info()
    assert info["entry_count"] == 0
    assert info["total_size_bytes"] == 0
    assert info["total_size_mb"] == 0.0
    assert info["entries"] == []


def test_cache_info_with_entries(tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import cache_info, write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        write_cache("https://other.com", SUCCESS_RESULT)
        info = cache_info()
    assert info["entry_count"] == 2
    assert info["total_size_bytes"] > 0
    assert info["total_size_mb"] >= 0
    assert len(info["entries"]) == 2
    for entry in info["entries"]:
        assert "hash" in entry
        assert entry["versions"] >= 1
        assert entry["size_bytes"] > 0
        assert entry["size_kb"] > 0
        assert entry["latest"].endswith(".json.gz")
        assert entry["latest_age_hours"] is not None


def test_cache_info_nonexistent_dir():
    with patch("app.cache.CACHE_DIR", "/nonexistent/path"):
        from app.cache import cache_info

        info = cache_info()
    assert info["entry_count"] == 0


def test_get_cache_endpoint(client, tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        resp = client.get("/api/v1/cache", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_count"] == 1
        assert data["total_size_bytes"] > 0
        assert len(data["entries"]) == 1


def test_get_cache_endpoint_requires_auth(client):
    resp = client.get("/api/v1/cache")
    assert resp.status_code == 403


def test_delete_cache_endpoint(client, tmp_path):
    with patch("app.cache.CACHE_DIR", str(tmp_path)):
        from app.cache import write_cache

        write_cache("https://example.com", SUCCESS_RESULT)
        write_cache("https://other.com", SUCCESS_RESULT)
        resp = client.delete("/api/v1/cache", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["entries_removed"] > 0
        assert data["size_freed_mb"] >= 0


def test_delete_cache_endpoint_requires_auth(client):
    resp = client.delete("/api/v1/cache")
    assert resp.status_code == 403
