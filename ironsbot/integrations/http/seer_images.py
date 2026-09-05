# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError

from ironsbot.services.seer.images import ImageSourceError, ImageSourceStatusError

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
_FALLBACK_KINDS = frozenset({"mintmark", "pet_body", "pet_head"})


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
        last_error: ImageSourceError | None = None
        for url in self._urls_for(kind, key):
            try:
                return await self._get(
                    self._clients.origin if kind == "preview" else self._clients.cache,
                    url,
                )
            except (HTTPStatusError, RequestError) as error:  # noqa: PERF203
                last_error = _image_source_error(error)
        error = last_error or ImageSourceError("所有图片 URL 均请求失败")
        if fallback and kind in _FALLBACK_KINDS:
            return await self._fallback(error)
        raise error

    def _urls_for(self, kind: ImageKind, key: str) -> tuple[str, ...]:
        paths = _PINNED_ASSET_PATHS.get(kind)
        if paths is None:
            return tuple(template.format(key) for template in _URLS[kind])
        snapshot = self._asset_snapshot_getter()
        if snapshot is None:
            raise ImageSourceError("当前数据版本缺少已验证的渲染素材清单")
        root = (
            "https://raw.githubusercontent.com/"
            f"{snapshot.repository}/{snapshot.revision}/"
        )
        return tuple(f"{root}{path.format(key)}" for path in paths)

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

    async def _fallback(self, error: ImageSourceError) -> bytes:
        return await self.fetch_url(f"https://dummyimage.com/300&text={error}")


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
