# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from httpx import AsyncClient, HTTPStatusError, RequestError

from ironsbot.services.seer.images import (
    ImageSourceError,
    ImageSourceStatusError,
    MissingImageRepositoryError,
    PreparedImageRequest,
    placeholder_image,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.services.seer.images import (
        AssetRepositoryKind,
        ImageKind,
        PublishedRenderAssetSnapshot,
    )

_PINNED_ASSET_PATHS: dict[ImageKind, tuple[tuple[AssetRepositoryKind, str], ...]] = {
    "autocard_card": (("default", "newseer/assets/art/autocard/texture/cards/{}.png"),),
    "autocard_role": (
        ("default", "newseer/assets/art/autocard/texture/roles/card/{}.png"),
    ),
    "battle_effect": (
        (
            "battle_effect",
            "newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
        ),
    ),
    "common": (("default", "newseer/assets/art/ui/common/{}.png"),),
    "element_type": (("element_type", "newseer/assets/art/ui/assets/pettype/{}.png"),),
    "equip": (("equip", "newseer/assets/art/ui/assets/item/cloth/prev/{}.png"),),
    "item": (
        ("item", "newseer/assets/art/ui/assets/item/doodle/icon/{}.png"),
        ("item", "newseer/assets/art/ui/assets/item/petitem/icon/{}.png"),
        ("item", "newseer/assets/art/ui/assets/item/skillstone/icon/{}.png"),
        ("item", "newseer/assets/art/ui/assets/item/throw/icon/{}.png"),
        ("item", "newseer/assets/art/ui/assets/item/userinfo/icon/{}.png"),
    ),
    "mintmark": (("mintmark", "newseer/assets/art/ui/assets/countermark/icon/{}.png"),),
    "mount": (
        ("default", "newseer/assets/art/ui/assets/item/cloth/prev/{}.png"),
        ("default", "newseer/assets/art/ui/assets/item/cloth/icon/{}.png"),
        ("mount", "mount/{}.png"),
    ),
    "pet_body": (("pet_body", "newseer/assets/art/ui/assets/pet/body/{}.png"),),
    "pet_head": (("pet_head", "newseer/assets/art/ui/assets/pet/head/{}.png"),),
    "sign_buff": (
        ("sign_buff", "newseer/assets/art/ui/assets/battleeffect/signbuff/{}.png"),
    ),
    "soulmark_icon": (
        ("default", "newseer/assets/art/ui/assets/effecticon/{}.png"),
    ),
    "suit": (("suit", "newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png"),),
    "title": (("title", "newseer/assets/art/ui/assets/achieve/title/{}.png"),),
}
_PINNED_ASSET_ROOTS = (
    "https://raw.githubusercontent.com/{repository}/{revision}/",
    "https://cdn.jsdelivr.net/gh/{repository}@{revision}/",
)
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
        snapshot = self._asset_snapshot_getter()
        if snapshot is None:
            raise ImageSourceError("当前数据版本缺少已验证的渲染素材清单")
        urls = self._urls_for(kind, key, snapshot)
        return PreparedImageRequest(
            identity=snapshot.cache_identity,
            fetch=partial(self._fetch_urls, urls),
            fallback=partial(placeholder_image, kind) if fallback else None,
        )

    async def _fetch_urls(
        self,
        urls: tuple[str, ...],
    ) -> bytes:
        last_error: ImageSourceError | None = None
        for url in urls:
            try:
                return await self._get(
                    self._clients.cache,
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
        snapshot: PublishedRenderAssetSnapshot,
    ) -> tuple[str, ...]:
        urls: list[str] = []
        for repository_kind, path in _PINNED_ASSET_PATHS[kind]:
            repository = snapshot.repository_for(repository_kind)
            if repository is None:
                continue
            roots = (
                root.format(
                    repository=repository.repository,
                    revision=repository.revision,
                )
                for root in _PINNED_ASSET_ROOTS
            )
            urls.extend(f"{root}{path.format(key)}" for root in roots)
        if not urls:
            raise MissingImageRepositoryError(kind)
        return tuple(dict.fromkeys(urls))

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
