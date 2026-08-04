import os
from pathlib import Path

from ironsbot.integrations.storage.render_cache import (
    UNKNOWN_RENDER_CACHE_VERSION,
    FileRenderCache,
)


def _test_cache(
    cache_dir: Path,
    *,
    max_size_bytes: int = 1024,
    version: str = "2026-06-12T00:00:00",
) -> FileRenderCache:
    return FileRenderCache(
        cache_dir,
        max_size_bytes,
        version_getter=lambda: version,
    )


def test_render_cache_get_and_put_are_scoped_by_db_version(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path)

    cache.put("pet_info", "25", b"png-data")

    assert cache.get("pet_info", "25") == b"png-data"
    assert cache.get("pet_info", "26") is None
    assert len(list(tmp_path.glob("*.bin"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_render_cache_skips_unknown_db_version(tmp_path: Path) -> None:
    cache_dir = tmp_path / "render-cache"
    cache = _test_cache(cache_dir, version=UNKNOWN_RENDER_CACHE_VERSION)

    cache.put("pet_info", "25", b"png-data")

    assert cache.get("pet_info", "25") is None
    assert not cache_dir.exists()


def test_render_cache_cleanup_removes_least_recently_used_entry(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path, max_size_bytes=5)

    cache.put("pet_info", "old", b"old")
    old_asset = next(tmp_path.glob("*.bin"))
    os.utime(old_asset, (1, 1))
    cache.put("pet_info", "new", b"new")

    assert cache.get("pet_info", "old") is None
    assert cache.get("pet_info", "new") == b"new"


def test_render_cache_discards_corrupt_entry(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path)
    cache.put("pet_info", "25", b"png-data")
    next(tmp_path.glob("*.bin")).write_bytes(b"corrupt")

    assert cache.get("pet_info", "25") is None
