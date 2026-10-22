# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import httpx
import pytest

from ironsbot.integrations.htmlkit_resources import HtmlkitResources
from ironsbot.integrations.http.clients import HttpClients

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_renderer_resources_use_owned_client_and_close_with_application() -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, content=b"resource")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as origin,
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as cache,
    ):
        resources = HtmlkitResources(HttpClients(cache, origin))
        image = await resources.image("https://example.test/image.png")
        assert image == b"resource"
        assert await resources.css("https://example.test/style.css") == "resource"
        assert requests == ["/image.png", "/style.css"]
        assert not origin.is_closed
        await resources.clients.close()
        assert origin.is_closed and cache.is_closed


@pytest.mark.asyncio
async def test_renderer_resources_preserve_redirects() -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/image":
            return httpx.Response(302, headers={"location": "/image.png"})
        return httpx.Response(200, content=b"image")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        resources = HtmlkitResources(HttpClients(client, client))
        assert await resources.image("https://example.test/image") == b"image"
        assert requests == ["/image", "/image.png"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection", "timeout", "decode"])
async def test_renderer_resource_failures_are_local_and_logs_are_redacted(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    url = "https://example.test/style.css?credential=private-test-value"

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "connection":
            raise httpx.ConnectError(url, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout(url, request=request)
        return httpx.Response(200, content=b"\xff")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        resources = HtmlkitResources(HttpClients(client, client))
        with caplog.at_level(logging.WARNING, logger="ironsbot"):
            assert await resources.css(url) is None
        assert caplog.records
        assert url not in caplog.text
        assert "private-test-value" not in caplog.text


@pytest.mark.asyncio
async def test_renderer_resources_propagate_cancellation() -> None:
    started = asyncio.Event()

    async def respond(_request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        resources = HtmlkitResources(HttpClients(client, client))
        task = asyncio.create_task(resources.image("https://example.test/image.png"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_renderer_local_and_data_resources_reuse_backend_fetchers(
    tmp_path: Path,
) -> None:
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=())

    image = tmp_path / "image.bin"
    image.write_bytes(b"image")
    css = tmp_path / "style.css"
    css.write_text(".test { color: red; }", encoding="utf-8")

    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("local and data resources must not perform HTTP requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        resources = HtmlkitResources(HttpClients(client, client))
        assert await resources.image(f"file://{image.as_posix()}") == b"image"
        style = await resources.css(f"file://{css.as_posix()}")
        assert style == ".test { color: red; }"
        assert await resources.image("data:image/png;base64,aW1hZ2U=") == b"image"
        assert await resources.css("data:text/css,.test%20%7B%7D") == ".test {}"
        assert await resources.image("unsupported://resource") is None
        assert await resources.css("unsupported://resource") is None


@pytest.mark.skipif(
    os.environ.get("IRONSBOT_NATIVE_RENDER_TESTS") != "1",
    reason="opt-in native htmlkit/fontconfig acceptance",
)
def test_native_renderer_loads_owned_http_images_and_css(tmp_path: Path) -> None:
    font_config = tmp_path / "fonts.conf"
    font_dir = "C:/Windows/Fonts" if sys.platform == "win32" else "/usr/share/fonts"
    font_config.write_text(
        f"<fontconfig><dir>{font_dir}</dir>"
        f"<cachedir>{tmp_path.as_posix()}/font-cache</cachedir></fontconfig>",
        encoding="utf-8",
    )
    template = tmp_path / "page.j2"
    template.write_text(
        '<link rel="stylesheet" href="https://example.test/style.css">'
        '<body><img src="https://example.test/image.png"></body>',
        encoding="utf-8",
    )
    script = r"""
import asyncio, socket, sys
from io import BytesIO
from pathlib import Path
import httpx, nonebot
from PIL import Image

def forbidden(*args, **kwargs):
    raise AssertionError("native rendering must not access real network")

nonebot.init(_env_file=(), driver="~fastapi", fontconfig_file=sys.argv[1])
import nonebot_plugin_htmlkit as backend
backend.init_fontconfig()
assert backend.session is None
from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.integrations.htmlkit_resources import HtmlkitResources
from ironsbot.integrations.http.clients import HttpClients

asset = BytesIO()
Image.new("RGB", (32, 32), "#218a62").save(asset, format="PNG")
requests = []
def respond(request):
    requests.append(request.url.path)
    if request.url.path == "/style.css":
        return httpx.Response(200, content=(
            b"body { margin: 0; width: 96px; background: #fff; } "
            b"img { width: 32px; height: 32px; display: block; }"
        ))
    assert request.url.path == "/image.png"
    return httpx.Response(200, content=asset.getvalue())

async def main():
    socket.socket.connect = forbidden
    socket.create_connection = forbidden
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        resources = HtmlkitResources(HttpClients(client, client))
        result = await render_html_template(
            Path(sys.argv[1]).parent, "page.j2", {}, max_width=96, allow_refit=False,
            img_fetch_fn=resources.image, css_fetch_fn=resources.css,
        )
        image = Image.open(BytesIO(result)).convert("RGB")
        assert image.width == 96, image.size
        colors = dict((rgb, count) for count, rgb in image.getcolors(100000))
        assert colors.get((33, 138, 98), 0) >= 64, colors
        assert set(requests) == {"/style.css", "/image.png"}, requests
        assert backend.session is None
        image.save(Path(sys.argv[1]).parent / "owned-resources.png")
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(font_config)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
