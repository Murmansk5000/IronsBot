# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from ironsbot.integrations.storage.render_cache import UNKNOWN_RENDER_CACHE_VERSION
from ironsbot.integrations.storage.render_cache_version import RenderCacheVersion


def test_render_cache_version_tracks_data_and_rendering_inputs(tmp_path: Path) -> None:
    rendering_root = tmp_path / "rendering"
    template = rendering_root / "template.html.j2"
    rendering_root.mkdir()
    template.write_text("first", encoding="utf-8")

    first = RenderCacheVersion(lambda: "data-1", (rendering_root,))()
    template.write_text("second", encoding="utf-8")
    second = RenderCacheVersion(lambda: "data-1", (rendering_root,))()
    changed_data = RenderCacheVersion(lambda: "data-2", (rendering_root,))()

    assert first != second
    assert second != changed_data


def test_render_cache_version_stays_unknown_without_published_data_version(
    tmp_path: Path,
) -> None:
    assert (
        RenderCacheVersion(
            lambda: UNKNOWN_RENDER_CACHE_VERSION,
            (tmp_path,),
        )()
        == UNKNOWN_RENDER_CACHE_VERSION
    )


def test_render_cache_version_ignores_generated_python_bytecode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "rendering" / "renderer.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1", encoding="utf-8")
    first = RenderCacheVersion(lambda: "data", (source.parent,))()

    bytecode = source.parent / "__pycache__" / "renderer.cpython-310.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated")
    second = RenderCacheVersion(lambda: "data", (source.parent,))()

    assert first == second
