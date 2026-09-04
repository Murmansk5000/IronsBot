# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import cache
from io import BytesIO
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError
from PIL import Image, ImageDraw

from ironsbot.services.seer.images import ImageSourceError

if TYPE_CHECKING:
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.services.seer.images import ImageKind

_URLS: dict[ImageKind, tuple[str, ...]] = {
    "battle_effect": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
    ),
    "element_type": (
        "https://newseer.61.com/web/PetType/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/pettype/{}.png",
    ),
    "equip": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/cloth/prev/{}.png",
    ),
    "item": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/doodle/icon/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/petitem/icon/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/skillstone/icon/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/throw/icon/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/userinfo/icon/{}.png",
    ),
    "mintmark": (
        "https://newseer.61.com/web/countermark/icon/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/countermark/icon/{}.png",
    ),
    "pet_body": (
        "https://newseer.61.com/web/monster/body/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/pet/body/{}.png",
    ),
    "pet_head": (
        "https://newseer.61.com/web/monster/head/{}.png",
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/pet/head/{}.png",
    ),
    "preview": (
        "https://raw.githubusercontent.com/Murmansk-Seer/"
        "seer-unity-preview-img-dumper/main/img/preview.png",
        "https://cdn.jsdelivr.net/gh/Murmansk-Seer/"
        "seer-unity-preview-img-dumper@main/img/preview.png",
    ),
    "sign_buff": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/battleeffect/signbuff/{}.png",
    ),
    "suit": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",
    ),
    "title": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/achieve/title/{}.png",
    ),
}
_FALLBACK_KINDS = frozenset({"mintmark", "pet_body", "pet_head"})
_FALLBACK_SIZES: dict[ImageKind, int] = {
    "mintmark": 96,
    "pet_body": 300,
    "pet_head": 160,
}


class HttpSeerImageSource:
    def __init__(self, clients: HttpClients) -> None:
        self._clients = clients

    async def fetch(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        last_error: ImageSourceError | None = None
        for template in _URLS[kind]:
            try:
                return await self._get(
                    self._clients.origin if kind == "preview" else self._clients.cache,
                    template.format(key),
                    serialize=kind != "preview",
                )
            except (HTTPStatusError, RequestError) as error:  # noqa: PERF203
                last_error = _image_source_error(error)
        error = last_error or ImageSourceError("所有图片 URL 均请求失败")
        if fallback and kind in _FALLBACK_KINDS:
            return _local_fallback_image(kind)
        raise error

    async def fetch_url(self, url: str) -> bytes:
        try:
            return await self._get(self._clients.origin, url, serialize=False)
        except (HTTPStatusError, RequestError) as error:
            raise _image_source_error(error) from error

    async def _get(
        self,
        client: AsyncClient,
        url: str,
        *,
        serialize: bool,
    ) -> bytes:
        if serialize:
            async with self._clients.cache_lock:
                response = await client.get(url)
        else:
            response = await client.get(url)
        response.raise_for_status()
        return response.content

def _image_source_error(
    error: HTTPStatusError | RequestError,
) -> ImageSourceError:
    if isinstance(error, HTTPStatusError):
        return ImageSourceError(
            f"{error.response.status_code} {error.response.reason_phrase}"
        )
    detail = str(error).strip() or type(error).__name__
    return ImageSourceError(f"{detail} ({error.request.url})")


@cache
def _local_fallback_image(kind: ImageKind) -> bytes:
    """Return a valid local PNG when an optional visual asset is unavailable."""
    size = _FALLBACK_SIZES[kind]
    image = Image.new("RGBA", (size, size), (26, 48, 78, 255))
    draw = ImageDraw.Draw(image)
    inset = max(3, size // 16)
    width = max(2, size // 24)
    draw.rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        outline=(94, 150, 216, 255),
        width=width,
    )
    draw.line(
        (inset * 2, inset * 2, size - inset * 2, size - inset * 2),
        fill=(94, 150, 216, 255),
        width=width,
    )
    draw.line(
        (size - inset * 2, inset * 2, inset * 2, size - inset * 2),
        fill=(94, 150, 216, 255),
        width=width,
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
