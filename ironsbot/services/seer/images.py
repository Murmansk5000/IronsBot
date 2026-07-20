# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Literal, Protocol

ImageKind = Literal[
    "battle_effect",
    "element_type",
    "equip",
    "item",
    "mintmark",
    "pet_body",
    "pet_head",
    "preview",
    "suit",
    "title",
]


class ImageSourceError(RuntimeError):
    pass


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
class ImageFetchResult:
    data: bytes | None = None
    error: str = ""


async def fetch_optional_image(
    images: SeerImageSource,
    kind: ImageKind,
    key: str,
) -> ImageFetchResult:
    try:
        return ImageFetchResult(
            data=await images.fetch(kind, key, fallback=False)
        )
    except ImageSourceError as error:
        return ImageFetchResult(error=f"❌获取图片失败！原因：{error}")


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
