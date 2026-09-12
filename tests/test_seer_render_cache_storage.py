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

    cache.entry("pet_info", "25").put(b"png-data")

    assert cache.entry("pet_info", "25").get() == b"png-data"
    assert cache.entry("pet_info", "26").get() is None
    assert len(list(tmp_path.glob("*.bin"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_bound_render_cache_keeps_late_writes_in_original_release(
    tmp_path: Path,
) -> None:
    cache = _test_cache(tmp_path, version="old")
    cache.entry("pet_info", "1").put(b"unbound-render")
    old = cache.bind("old", lambda _: True).entry("pet_info", "1")
    fresh = cache.bind("new", lambda _: True).entry("pet_info", "1")
    assert old.get() is None
    fresh.put(b"new-render")
    old.put(b"late-old-render")
    assert fresh.get() == b"new-render"
    assert old.get() == b"late-old-render"
    assert (
        cache.bind("old", lambda _: True).entry("pet_info", "1").get()
        == b"late-old-render"
    )
    unavailable = cache.bind("old", lambda _: False).entry("pet_info", "1")
    unavailable.put(b"unavailable")
    assert unavailable.get() is None
    unknown = cache.bind("unknown", lambda _: True).entry("pet_info", "1")
    unknown.put(b"unknown")
    assert unknown.get() is None


def test_render_cache_skips_unknown_db_version(tmp_path: Path) -> None:
    cache_dir = tmp_path / "render-cache"
    cache = _test_cache(cache_dir, version=UNKNOWN_RENDER_CACHE_VERSION)

    cache.entry("pet_info", "25").put(b"png-data")

    assert cache.entry("pet_info", "25").get() is None
    assert not cache_dir.exists()


def test_render_cache_skips_categories_without_complete_manifest_scope(
    tmp_path: Path,
) -> None:
    cache = FileRenderCache(
        tmp_path,
        1024,
        version_getter=lambda: "release",
        category_available=lambda category: category == "pet_info",
    )

    cache.entry("new_content", "request").put(b"png-data")

    assert cache.entry("new_content", "request").get() is None
    assert list(tmp_path.glob("*.bin")) == []


def test_render_cache_cleanup_removes_least_recently_used_entry(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path, max_size_bytes=5)

    cache.entry("pet_info", "old").put(b"old")
    old_asset = next(tmp_path.glob("*.bin"))
    os.utime(old_asset, (1, 1))
    cache.entry("pet_info", "new").put(b"new")

    assert cache.entry("pet_info", "old").get() is None
    assert cache.entry("pet_info", "new").get() == b"new"


def test_render_cache_discards_corrupt_entry(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path)
    cache.entry("pet_info", "25").put(b"png-data")
    next(tmp_path.glob("*.bin")).write_bytes(b"corrupt")

    assert cache.entry("pet_info", "25").get() is None


def test_render_entry_does_not_publish_across_version_changes(tmp_path: Path) -> None:
    version = "old"
    cache = FileRenderCache(tmp_path, 1024, version_getter=lambda: version)
    old = cache.entry("pet_info", "25")
    assert old.get() is None
    version = "new"
    old.put(b"mixed-version-render")
    assert old.get() is None
    fresh = cache.entry("pet_info", "25")
    assert fresh.get() is None
    fresh.put(b"new-render")
    assert fresh.get() == b"new-render"
    old.put(b"late-old-render")
    assert fresh.get() == b"new-render"
    version = "old"
    assert cache.entry("pet_info", "25").get() is None


def test_render_entry_cannot_gain_scope_after_preparation(tmp_path: Path) -> None:
    available = False
    cache = FileRenderCache(
        tmp_path,
        1024,
        version_getter=lambda: "release",
        category_available=lambda _category: available,
    )
    unavailable = cache.entry("pet_info", "25")
    available = True
    unavailable.put(b"unproven-render")
    assert cache.entry("pet_info", "25").get() is None
    fresh = cache.entry("pet_info", "25")
    available = False
    fresh.put(b"revoked-scope-render")
    assert fresh.get() is None
    assert not list(tmp_path.glob("*.bin"))
