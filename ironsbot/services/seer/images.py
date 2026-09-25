# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from io import BytesIO
from typing import TYPE_CHECKING, Literal, Protocol

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)
IMAGE_UNAVAILABLE_MESSAGE = "图片素材获取失败，暂时无法显示。"

ImageKind = Literal[
    "autocard_card",
    "autocard_role",
    "battle_effect",
    "common",
    "element_type",
    "equip",
    "item",
    "mintmark",
    "mount",
    "pet_body",
    "pet_head",
    "sign_buff",
    "soulmark_icon",
    "suit",
    "title",
]
AssetRepositoryKind = ImageKind | Literal["default"]

_PLACEHOLDER_SIZES: dict[ImageKind, int] = {
    "autocard_card": 160,
    "autocard_role": 160,
    "battle_effect": 96,
    "common": 96,
    "element_type": 64,
    "equip": 160,
    "item": 96,
    "mintmark": 96,
    "mount": 160,
    "pet_body": 300,
    "pet_head": 160,
    "sign_buff": 96,
    "soulmark_icon": 96,
    "suit": 160,
    "title": 160,
}

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


@dataclass(frozen=True, slots=True)
class ImageFetchResult:
    data: bytes | None = None
    error: str = ""
    status_code: int | None = None


ImageFailureReporter = Callable[[str, str, ImageSourceError], Awaitable[None]]


async def fetch_optional_image(
    images: SeerImageSource,
    kind: ImageKind,
    key: str,
    report_failure: ImageFailureReporter | None = None,
) -> ImageFetchResult:
    try:
        return ImageFetchResult(data=await images.fetch(kind, key, fallback=False))
    except ImageSourceError as error:
        logger.warning(
            "Seer image source failed: kind=%s key=%s error_type=%s",
            kind,
            key,
            type(error).__name__,
        )
        if report_failure is not None:
            await report_failure(kind, key, error)
        return ImageFetchResult(
            error=IMAGE_UNAVAILABLE_MESSAGE,
            status_code=(
                error.status_code if isinstance(error, ImageSourceStatusError) else None
            ),
        )


@cache
def placeholder_image(kind: ImageKind) -> bytes:
    """Return a presentation-only marker for one unavailable image asset."""

    size = _PLACEHOLDER_SIZES[kind]
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


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
