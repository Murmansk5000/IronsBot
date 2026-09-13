# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

ImageKind = Literal[
    "battle_effect",
    "element_type",
    "equip",
    "item",
    "mintmark",
    "mount",
    "pet_body",
    "pet_head",
    "preview",
    "sign_buff",
    "suit",
    "title",
]
AssetRepositoryKind = ImageKind | Literal["default"]

_ASSET_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ASSET_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class PublishedAssetRepository:
    repository: str
    revision: str


@dataclass(frozen=True, slots=True)
class PublishedRenderAssetSnapshot:
    """Immutable asset trees declared by one loaded SeerAPI release."""

    repositories: Mapping[str, PublishedAssetRepository]
    manifest_revision: str
    scopes: frozenset[str]

    @property
    def cache_identity(self) -> str:
        repositories = ",".join(
            f"{kind}={source.repository}@{source.revision}"
            for kind, source in sorted(self.repositories.items())
        )
        return f"{repositories}:{self.manifest_revision}"

    def repository_for(
        self, kind: AssetRepositoryKind
    ) -> PublishedAssetRepository | None:
        return self.repositories.get(kind, self.repositories.get("default"))


def parse_published_render_asset_snapshot(  # noqa: PLR0911 - strict boundary parser
    metadata: Mapping[str, str],
    *,
    contract_version: str,
) -> PublishedRenderAssetSnapshot | None:
    """Validate the narrow release metadata contract used by image adapters."""

    if metadata.get("render_asset_manifest_contract_version") != contract_version:
        return None
    manifest_revision = metadata.get("render_asset_manifest_revision", "")
    try:
        raw_repositories = json.loads(
            metadata.get("render_asset_manifest_repositories", "")
        )
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_repositories, dict) or not manifest_revision:
        return None
    repositories: dict[str, PublishedAssetRepository] = {}
    for kind, raw_source in raw_repositories.items():
        if not isinstance(kind, str) or not isinstance(raw_source, dict):
            return None
        repository = raw_source.get("repository")
        revision = raw_source.get("revision")
        if (
            not isinstance(repository, str)
            or not isinstance(revision, str)
            or not _ASSET_REPOSITORY_PATTERN.fullmatch(repository)
            or not _ASSET_REVISION_PATTERN.fullmatch(revision)
        ):
            return None
        repositories[kind] = PublishedAssetRepository(repository, revision)
    if "default" not in repositories:
        return None
    return PublishedRenderAssetSnapshot(
        repositories=repositories,
        manifest_revision=manifest_revision,
        scopes=frozenset(),
    )


class ImageSourceError(RuntimeError):
    pass


class ImageSourceStatusError(ImageSourceError):
    """An image request that failed with a concrete HTTP status."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"{status_code} {reason}")
        self.status_code = status_code


class MissingImageRepositoryError(ImageSourceError):
    def __init__(self, kind: ImageKind) -> None:
        super().__init__(f"当前数据版本未声明 {kind} 素材仓库")


class SeerImageSource(Protocol):
    async def fetch(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes: ...

    async def fetch_url(self, url: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PreparedImageRequest:
    """One immutable source identity paired with its exact download operation."""

    identity: str
    fetch: Callable[[], Awaitable[bytes]]
    # Presentation-only fallback; its bytes must never enter the asset cache.
    fallback: Callable[[], bytes] | None = None


class SeerImageRequestSource(Protocol):
    def prepare(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool,
    ) -> PreparedImageRequest: ...

    async def fetch_url(self, url: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ImageFetchResult:
    data: bytes | None = None
    error: str = ""


async def fetch_optional_image(
    images: SeerImageSource,
    kind: ImageKind,
    key: str,
) -> ImageFetchResult:
    try:
        return ImageFetchResult(data=await images.fetch(kind, key, fallback=False))
    except ImageSourceError as error:
        return ImageFetchResult(error=f"❌获取图片失败！原因：{error}")


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
