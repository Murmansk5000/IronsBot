# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

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
    "autocard_chip": (("default", "newseer/assets/game/ui/autocard/s2chip/{}.png"),),
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
    "soulmark_icon": (("default", "newseer/assets/art/ui/assets/effecticon/{}.png"),),
    "suit": (("suit", "newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png"),),
    "title": (("title", "newseer/assets/art/ui/assets/achieve/title/{}.png"),),
}
_PINNED_ASSET_ROOTS = (
    "https://raw.githubusercontent.com/{repository}/{revision}/",
    "https://cdn.jsdelivr.net/gh/{repository}@{revision}/",
)
_MISSING_IMAGE_STATUSES = frozenset({404, 410})
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_LFS_POINTER = re.compile(
    rb"version https://git-lfs.github.com/spec/v1\r?\n"
    rb"oid sha256:([0-9a-f]{64})\r?\nsize ([0-9]+)\r?\n?"
)
_AUDITED_PRIMARY_REPOSITORY = "Murmansk-Seer/seer-unity-assets"
_CNB_SUIT_REPOSITORY = "HurryWang/seer-unity-suit-assets"
_CNB_SUIT_REF = "main"
_CNB_BODY_REPOSITORY = "HurryWang/seer-unity-img-assets"
_CNB_BODY_REF = "master"
_CNB_INVALID_IMAGE_MESSAGE = "CNB 素材不是 PNG 图片"
_CNB_INVALID_LFS_POINTER_MESSAGE = "CNB 立绘 LFS 指针格式无效"
_CNB_MISSING_LFS_URL_MESSAGE = "CNB 立绘 LFS 下载地址缺失"
_CNB_INVALID_LFS_URL_MESSAGE = "CNB 立绘 LFS 下载地址无效"
_CNB_INVALID_LFS_HOST_MESSAGE = "CNB 立绘 LFS 下载域名无效"
_CNB_LFS_CHECKSUM_MESSAGE = "CNB 立绘 LFS 校验失败"
_CNB_BLOB_MISMATCH_MESSAGE = "CNB 素材与当前发布版本不一致"
_CNB_FALLBACK_PATHS: dict[ImageKind, tuple[str, str, str]] = {
    "battle_effect": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "battleeffect_abnormal/{}.png",
    ),
    "mintmark": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "countermark_icon/{}.png",
    ),
    "pet_body": (_CNB_BODY_REPOSITORY, _CNB_BODY_REF, "pet_body/{}.png"),
    "pet_head": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "defaultpackage_assets_art_ui_assets_pet_head/{}.png",
    ),
    "sign_buff": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "battleeffect_signbuff/{}.png",
    ),
    "soulmark_icon": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "effecticon/{}.png",
    ),
    "suit": (
        _CNB_SUIT_REPOSITORY,
        _CNB_SUIT_REF,
        "defaultpackage_assets_art_ui_assets_item_cloth_suiticon/{}.png",
    ),
}
_LOGGER = logging.getLogger(__name__)


class HttpSeerImageSource:
    def __init__(
        self,
        clients: HttpClients,
        *,
        asset_snapshot_getter: Callable[[], PublishedRenderAssetSnapshot | None],
        asset_blob_getter: Callable[
            [ImageKind, str, PublishedRenderAssetSnapshot], str | None
        ]
        | None = None,
    ) -> None:
        self._clients = clients
        self._asset_snapshot_getter = asset_snapshot_getter
        self._asset_blob_getter = asset_blob_getter

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
        cnb_url = self._cnb_url_for(kind, key, snapshot)
        return PreparedImageRequest(
            identity=snapshot.cache_identity,
            fetch=partial(self._fetch_urls, kind, key, snapshot, urls, cnb_url),
            fallback=partial(placeholder_image, kind) if fallback else None,
        )

    async def _fetch_urls(
        self,
        kind: ImageKind,
        key: str,
        snapshot: PublishedRenderAssetSnapshot,
        urls: tuple[str, ...],
        cnb_url: str | None,
    ) -> bytes:
        last_error: ImageSourceError | None = None
        non_missing_error: ImageSourceError | None = None
        for url in urls:
            try:
                return await self._get(
                    self._clients.cache,
                    url,
                )
            except (HTTPStatusError, RequestError) as error:  # noqa: PERF203
                last_error = _image_source_error(error)
                if (
                    not isinstance(last_error, ImageSourceStatusError)
                    or last_error.status_code not in _MISSING_IMAGE_STATUSES
                ):
                    non_missing_error = last_error
        if (
            non_missing_error is not None
            and cnb_url is not None
            and self._asset_blob_getter is not None
            and (expected_blob := self._asset_blob_getter(kind, key, snapshot))
        ):
            try:
                return await self._fetch_cnb(kind, cnb_url, expected_blob)
            except (HTTPStatusError, RequestError, ImageSourceError) as error:
                _LOGGER.warning(
                    "CNB image fallback failed: kind=%s error_type=%s",
                    kind,
                    type(error).__name__,
                )
        error = (
            non_missing_error
            or last_error
            or ImageSourceError("所有图片 URL 均请求失败")
        )
        raise error

    def _cnb_url_for(
        self,
        kind: ImageKind,
        key: str,
        snapshot: PublishedRenderAssetSnapshot,
    ) -> str | None:
        source = _CNB_FALLBACK_PATHS.get(kind)
        if source is None:
            return None
        repository_kind = _PINNED_ASSET_PATHS[kind][0][0]
        repository = snapshot.repository_for(repository_kind)
        if (
            repository is None
            or repository.repository != _AUDITED_PRIMARY_REPOSITORY
        ):
            return None
        cnb_repository, cnb_ref, path = source
        return (
            f"https://cnb.cool/{cnb_repository}/-/git/raw/{cnb_ref}/"
            f"imgs/{path.format(key)}"
        )

    async def _fetch_cnb(
        self, kind: ImageKind, url: str, expected_blob: str
    ) -> bytes:
        data = await self._get(self._clients.cache, url)
        pointer_matches = _git_blob(data) == expected_blob
        if kind == "pet_body" and data.startswith(
            b"version https://git-lfs.github.com"
        ):
            data = await self._fetch_cnb_lfs(data)
        if not pointer_matches and _git_blob(data) != expected_blob:
            raise ImageSourceError(_CNB_BLOB_MISMATCH_MESSAGE)
        if not data.startswith(_PNG_SIGNATURE):
            raise ImageSourceError(_CNB_INVALID_IMAGE_MESSAGE)
        return data

    async def _fetch_cnb_lfs(self, pointer: bytes) -> bytes:
        match = _LFS_POINTER.fullmatch(pointer)
        if match is None:
            raise ImageSourceError(_CNB_INVALID_LFS_POINTER_MESSAGE)
        oid = match.group(1).decode("ascii")
        size = int(match.group(2))
        response = await self._clients.cache.post(
            f"https://cnb.cool/{_CNB_BODY_REPOSITORY}.git/info/lfs/objects/batch",
            headers={
                "Accept": "application/vnd.git-lfs+json",
                "Content-Type": "application/vnd.git-lfs+json",
            },
            json={
                "operation": "download",
                "transfers": ["basic"],
                "objects": [{"oid": oid, "size": size}],
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
            download_url = payload["objects"][0]["actions"]["download"]["href"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise ImageSourceError(_CNB_MISSING_LFS_URL_MESSAGE) from error
        if not isinstance(download_url, str):
            raise ImageSourceError(_CNB_INVALID_LFS_URL_MESSAGE)
        parsed_url = urlsplit(download_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "lfs.cnb.cool":
            raise ImageSourceError(_CNB_INVALID_LFS_HOST_MESSAGE)
        data = await self._get(self._clients.cache, download_url)
        if len(data) != size or hashlib.sha256(data).hexdigest() != oid:
            raise ImageSourceError(_CNB_LFS_CHECKSUM_MESSAGE)
        return data

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


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(data)}\0".encode() + data, usedforsecurity=False
    ).hexdigest()
