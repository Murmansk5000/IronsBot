from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ironsbot.integrations import litehtml
from ironsbot.integrations.litehtml.local_resources import local_css, local_image

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.mark.parametrize("kind", ["version", "missing", "ambiguous"])
def test_native_abi_mismatch_fails_without_importing_a_plugin(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    package = SimpleNamespace(
        version="unsupported" if kind == "version" else litehtml.NATIVE_VERSION,
        files=(
            [
                Path("nonebot_plugin_htmlkit/core.pyd"),
                Path("nonebot_plugin_htmlkit/core.so"),
            ]
            if kind == "ambiguous"
            else []
        ),
        locate_file=lambda path: path,
    )
    monkeypatch.setattr(litehtml, "distribution", lambda _: package)
    with pytest.raises(RuntimeError, match=r"ABI version|missing or ambiguous"):
        litehtml._native_core.__wrapped__()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", [local_image, local_css])
@pytest.mark.parametrize(
    "url", ["data:bad", "data:base64,?", "file:///missing/render/file"]
)
async def test_bad_local_resource_is_local_and_does_not_raise(
    reader: Callable[[str], Awaitable[bytes | str | None]], url: str
) -> None:
    assert await reader(url) in (None, b"", "")


@pytest.mark.skipif(
    os.environ.get("IRONSBOT_NATIVE_RENDER_TESTS") != "1",
    reason="opt-in exact native PNG comparison with the pinned upstream API",
)
def test_independent_binding_preserves_upstream_png_bytes(tmp_path: Path) -> None:
    font_dir = "C:/Windows/Fonts" if sys.platform == "win32" else "/usr/share/fonts"
    (tmp_path / "fonts.conf").write_text(
        f"<fontconfig><dir>{font_dir}</dir>"
        f"<cachedir>{tmp_path.as_posix()}/font-cache</cachedir></fontconfig>",
        encoding="utf-8",
    )
    (tmp_path / "page.j2").write_text(
        '<body style="margin:0;width:360px;font-size:28px">'
        '<div style="font-weight:bold">{{ title }}</div>'
        '<img src="data:image/svg+xml,%3Csvg%3E%3C/svg%3E">'
        '<div style="color:red">{{ project_url }}</div></body>',
        encoding="utf-8",
    )
    script = r"""
import asyncio, os, sys
from pathlib import Path
root = Path(sys.argv[1])
os.environ["FONTCONFIG_FILE"] = str(root / "fonts.conf")
values = {"title": "IronsBot 中文渲染", "project_url": "https://example.test/project"}
if sys.argv[2] == "upstream":
    import nonebot
    nonebot.init(_env_file=(), fontconfig_file=str(root / "fonts.conf"))
    from nonebot_plugin_htmlkit import init_fontconfig, template_to_pic
    init_fontconfig()
    image = asyncio.run(template_to_pic(root, "page.j2", values,
        max_width=360, allow_refit=False))
else:
    sys.modules["nonebot"] = None
    from ironsbot.integrations.litehtml import initialize_fontconfig
    from ironsbot.integrations.htmlkit import render_html_template
    initialize_fontconfig()
    image = asyncio.run(render_html_template(root, "page.j2", values,
        max_width=360, allow_refit=False))
    assert "nonebot_plugin_htmlkit" not in sys.modules
(root / (sys.argv[2] + ".png")).write_bytes(image)
"""
    for backend in ("upstream", "independent"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), backend],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    upstream = (tmp_path / "upstream.png").read_bytes()
    assert upstream.startswith(bytes.fromhex("89504e470d0a1a0a"))
    assert (tmp_path / "independent.png").read_bytes() == upstream
