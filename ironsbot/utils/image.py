# SPDX-License-Identifier: MIT
import base64
import io
from collections.abc import Awaitable, Callable

from httpx import AsyncClient, HTTPStatusError, RequestError
from nonebot.params import Depends
from nonebot_plugin_saa import Image, MessageSegmentFactory, Text
from PIL import Image as PILImage

from .parse_arg import parse_string_arg


class GetImage:
    def __init__(
        self,
        *url_templates: str,
        fallback: Callable[[Exception], Awaitable[bytes]] | None = None,
        client_getter: Callable[[], AsyncClient],
    ) -> None:
        if not url_templates:
            raise ValueError("至少需要一个 URL 模板")

        self._client_getter = client_getter
        self.url_templates = url_templates
        self.fallback = fallback

    async def _fetch_image_bytes(self, url: str) -> bytes:
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


def flip_image_horizontal(data: bytes) -> bytes:
    with PILImage.open(io.BytesIO(data)) as img:
        flipped = img.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
        buf = io.BytesIO()
        flipped.save(buf, format=img.format or "PNG")
        return buf.getvalue()
