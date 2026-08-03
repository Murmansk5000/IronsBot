from pathlib import Path
from shutil import rmtree

from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.runtime.cache_paths import CachePaths


def test_cache_paths_do_not_create_directories_when_resolved(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    paths = CachePaths(root)

    assert not root.exists()
    assert paths.render_dir() == root / "render"
    assert not root.exists()
    assert not (root / "downloads").exists()
    assert not (root / "http").exists()
    assert not (root / "assets").exists()
    assert not (root / "runtime").exists()


def test_cache_paths_supports_each_disposable_category(tmp_path: Path) -> None:
    paths = CachePaths(tmp_path / "custom-cache")

    assert paths.downloads_dir() == tmp_path / "custom-cache" / "downloads"
    assert paths.http_dir() == tmp_path / "custom-cache" / "http"
    assert paths.assets_dir() == tmp_path / "custom-cache" / "assets"
    assert paths.runtime_dir() == tmp_path / "custom-cache" / "runtime"


def test_render_cache_recreates_deleted_cache_root(tmp_path: Path) -> None:
    paths = CachePaths(tmp_path / "cache")
    cache = FileRenderCache(
        paths.render_dir(),
        max_size_bytes=1024,
        db_version_getter=lambda: "version",
    )

    cache.put("pet_info", "25", b"first")
    assert paths.render_dir().exists()

    rmtree(paths.root)
    cache.put("pet_info", "25", b"second")

    assert cache.get("pet_info", "25") == b"second"
