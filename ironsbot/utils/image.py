# SPDX-License-Identifier: MIT
import asyncio
import base64
from collections.abc import Awaitable, Callable

from httpx import AsyncClient, HTTPStatusError, RequestError
from nonebot.params import Depends
from nonebot_plugin_saa import Image, MessageSegmentFactory, Text

from .parse_arg import parse_string_arg

_image_fetch_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


class MissingImageUrlTemplateError(ValueError):
    """Raised when a GetImage instance is created without URL templates."""


def _get_image_fetch_lock() -> asyncio.Lock:
    """Return a loop-local lock for shared image HTTP cache access."""
    loop = asyncio.get_running_loop()
    lock = _image_fetch_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _image_fetch_locks[loop] = lock
    return lock


class GetImage:
    def __init__(
        self,
        *url_templates: str,
        fallback: Callable[[Exception], Awaitable[bytes]] | None = None,
        client_getter: Callable[[], AsyncClient],
    ) -> None:
        if not url_templates:
            raise MissingImageUrlTemplateError

        self._client_getter = client_getter
        self.url_templates = url_templates
        self.fallback = fallback

    async def _fetch_image_bytes(self, url: str) -> bytes:
        # The shared hishel client writes response metadata into a SQLite cache.
        # Concurrent image downloads can otherwise collide inside the cache
        # transaction and raise "cannot start a transaction within a transaction".
        async with _get_image_fetch_lock():
            response = await self.client.get(url)
        response.raise_for_status()
        return response.content

    @property
    def client(self) -> AsyncClient:
        return self._client_getter()

    async def _create_image_segment_from_url(self, url: str) -> Image:
        return Image(await self._fetch_image_bytes(url))

    async def get_bytes(self, arg: str) -> bytes:
        """获取图片原始字节，依次尝试所有 URL 模板。"""
        last_error: Exception | None = None
        for template in self.url_templates:
            url = template.format(arg)
            try:
                return await self._fetch_image_bytes(url)
            except (HTTPStatusError, RequestError) as e:
                last_error = e
                continue
        error = last_error or RuntimeError("所有 URL 均请求失败")
        if self.fallback is not None:
            return await self.fallback(error)
        raise error

    async def get(self, arg: str) -> MessageSegmentFactory:
        last_error: Exception | None = None
        for template in self.url_templates:
            url = template.format(arg)
            try:
                return await self._create_image_segment_from_url(url)
            except (HTTPStatusError, RequestError) as e:
                last_error = e
                continue

        if isinstance(last_error, HTTPStatusError):
            code = last_error.response.status_code
            reason = last_error.response.reason_phrase
            return Text(f"❌获取图片失败！原因：{code} {reason}")
        return Text(f"❌获取图片失败！原因：{last_error}")

    async def __call__(
        self,
        arg: str = Depends(parse_string_arg),
    ) -> MessageSegmentFactory:
        if not arg:
            return Text("❌获取图片失败！原因：参数不能为空")

        return await self.get(arg)


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{b64}"
