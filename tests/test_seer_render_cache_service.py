import os
import subprocess
import sys
from pathlib import Path

from ironsbot.services.seer.render_cache import (
    UNKNOWN_RENDER_CACHE_VERSION,
    RenderCache,
)


def _test_cache(
    cache_dir: Path,
    *,
    max_size_bytes: int = 1024,
    version: str = "2026-06-12T00:00:00",
) -> RenderCache:
    return RenderCache(
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


def test_render_cache_service_imports_without_nonebot_bootstrap() -> None:
    script = """
import importlib

importlib.import_module("ironsbot.services.seer.render_cache")
print("render cache import ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
