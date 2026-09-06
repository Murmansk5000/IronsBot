import os
from pathlib import Path

import pytest

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
        db_version_getter=lambda: version,
    )


def test_render_cache_get_and_put_are_scoped_by_db_version(tmp_path: Path) -> None:
    cache = _test_cache(tmp_path)

    cache.put("pet_info", "25", b"png-data")

    assert cache.get("pet_info", "25") == b"png-data"
    assert cache.get("pet_info", "26") is None
    cache_files = list(tmp_path.iterdir())
    assert len(cache_files) == 1
    assert cache_files[0].name.startswith("pet_info_25_")
    assert cache_files[0].name.endswith(".png")


def test_render_cache_skips_unknown_db_version(tmp_path: Path) -> None:
    cache_dir = tmp_path / "render-cache"
    cache = _test_cache(cache_dir, version=UNKNOWN_RENDER_CACHE_VERSION)

    cache.put("pet_info", "25", b"png-data")

    assert cache.get("pet_info", "25") is None
    assert not cache_dir.exists()


def test_render_cache_is_scoped_by_current_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _test_cache(tmp_path)
    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://github.com/owner-a/IronsBot")
    cache.put("pet_info", "25", b"owner-a")

    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://github.com/owner-b/IronsBot")

    assert cache.get("pet_info", "25") is None


def test_render_cache_cleanup_removes_oldest_files_first(tmp_path: Path) -> None:
    old_file = tmp_path / "old.png"
    new_file = tmp_path / "new.png"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    os.utime(old_file, (1, 1))
    os.utime(new_file, (2, 2))
    cache = _test_cache(tmp_path, max_size_bytes=5)

    cache.cleanup()

    assert not old_file.exists()
    assert new_file.exists()
