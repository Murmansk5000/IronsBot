# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import cache, partial
from io import BytesIO
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError
from PIL import Image, ImageDraw

from ironsbot.services.seer.images import (
    ImageSourceError,
    ImageSourceStatusError,
    PreparedImageRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.services.seer.images import (
        ImageKind,
        PublishedRenderAssetSnapshot,
    )

_URLS: dict[ImageKind, tuple[str, ...]] = {
    "battle_effect": (
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
    ),
    "preview": (
        "https://raw.githubusercontent.com/Murmansk-Seer/"
        "seer-unity-preview-img-dumper/main/img/preview.png",
        "https://cdn.jsdelivr.net/gh/Murmansk-Seer/"
        "seer-unity-preview-img-dumper@main/img/preview.png",
    ),
}
_PINNED_ASSET_PATHS: dict[ImageKind, tuple[str, ...]] = {
    "element_type": ("newseer/assets/art/ui/assets/pettype/{}.png",),
    "equip": ("newseer/assets/art/ui/assets/item/cloth/prev/{}.png",),
    "item": (
        "newseer/assets/art/ui/assets/item/doodle/icon/{}.png",
        "newseer/assets/art/ui/assets/item/petitem/icon/{}.png",
        "newseer/assets/art/ui/assets/item/skillstone/icon/{}.png",
        "newseer/assets/art/ui/assets/item/throw/icon/{}.png",
        "newseer/assets/art/ui/assets/item/userinfo/icon/{}.png",
    ),
    "mintmark": ("newseer/assets/art/ui/assets/countermark/icon/{}.png",),
    "pet_body": ("newseer/assets/art/ui/assets/pet/body/{}.png",),
    "pet_head": ("newseer/assets/art/ui/assets/pet/head/{}.png",),
    "sign_buff": ("newseer/assets/art/ui/assets/battleeffect/signbuff/{}.png",),
    "suit": ("newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",),
    "title": ("newseer/assets/art/ui/assets/achieve/title/{}.png",),
}
_PINNED_ASSET_ROOTS = (
    "https://raw.githubusercontent.com/{repository}/{revision}/",
    "https://cdn.jsdelivr.net/gh/{repository}@{revision}/",
)
_FALLBACK_KINDS = frozenset({"mintmark", "pet_body", "pet_head"})
_FALLBACK_SIZES: dict[ImageKind, int] = {
    "mintmark": 96,
    "pet_body": 300,
    "pet_head": 160,
}


class HttpSeerImageSource:
    def __init__(
        self,
        clients: HttpClients,
        *,
        asset_snapshot_getter: Callable[[], PublishedRenderAssetSnapshot | None],
    ) -> None:
        self._clients = clients
        self._asset_snapshot_getter = asset_snapshot_getter

    async def fetch(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        request = self.prepare(kind, key, fallback=fallback)
        try:
            return await request.fetch()
        except ImageSourceError:
            if request.fallback is None:
                raise
            return request.fallback()

    def prepare(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool,
    ) -> PreparedImageRequest:
        snapshot = (
            self._asset_snapshot_getter() if kind in _PINNED_ASSET_PATHS else None
        )
        urls = self._urls_for(kind, key, snapshot)
        return PreparedImageRequest(
            identity=snapshot.cache_identity if snapshot is not None else "unversioned",
            fetch=partial(self._fetch_urls, kind, urls),
            fallback=(
                partial(_local_fallback_image, kind)
                if fallback and kind in _FALLBACK_KINDS
                else None
            ),
        )

    async def _fetch_urls(
        self,
        kind: ImageKind,
        urls: tuple[str, ...],
    ) -> bytes:
        last_error: ImageSourceError | None = None
        for url in urls:
            try:
                return await self._get(
                    self._clients.origin if kind == "preview" else self._clients.cache,
                    url,
                )
            except (HTTPStatusError, RequestError) as error:  # noqa: PERF203
                last_error = _image_source_error(error)
        error = last_error or ImageSourceError("所有图片 URL 均请求失败")
        raise error

    def _urls_for(
        self,
        kind: ImageKind,
        key: str,
        snapshot: PublishedRenderAssetSnapshot | None,
    ) -> tuple[str, ...]:
        paths = _PINNED_ASSET_PATHS.get(kind)
        if paths is None:
            return tuple(template.format(key) for template in _URLS[kind])
        if snapshot is None:
            raise ImageSourceError("当前数据版本缺少已验证的渲染素材清单")
        roots = tuple(
            template.format(
                repository=snapshot.repository,
                revision=snapshot.revision,
            )
            for template in _PINNED_ASSET_ROOTS
        )
        return tuple(
            f"{root}{path.format(key)}"
            for path in paths
            for root in roots
        )

    async def fetch_url(self, url: str) -> bytes:
        try:
            return await self._get(self._clients.origin, url)
        except (HTTPStatusError, RequestError) as error:
            raise _image_source_error(error) from error

    async def _get(
        self,
        client: AsyncClient,
        url: str,
    ) -> bytes:
        response = await client.get(url)
        response.raise_for_status()
        return response.content

def _image_source_error(
    error: HTTPStatusError | RequestError,
) -> ImageSourceError:
    if isinstance(error, HTTPStatusError):
        return ImageSourceStatusError(
            error.response.status_code,
            error.response.reason_phrase,
        )
    detail = str(error).strip() or type(error).__name__
    return ImageSourceError(f"{detail} ({error.request.url})")


@cache
def _local_fallback_image(kind: ImageKind) -> bytes:
    """Return a local placeholder, never a replacement for official artwork."""
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
