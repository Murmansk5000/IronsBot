# SPDX-License-Identifier: GPL-3.0-or-later
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_WEEKLY_PREVIEW_IMAGE_URL = (
    "https://raw.githubusercontent.com/Murmansk-Seer/"
    "seer-unity-preview-img-dumper/main/img/preview.png"
)
DEFAULT_WEEKLY_PREVIEW_IMAGE_URLS = (
    DEFAULT_WEEKLY_PREVIEW_IMAGE_URL,
    "https://raw.githubusercontent.com/Murmansk-Seer/"
    "seer-unity-preview-img-dumper/main/img/imgPreview_1.png",
)
DEFAULT_WEEKLY_PREVIEW_SOURCE_URL = (
    "https://github.com/Murmansk-Seer/seer-unity-preview-img-dumper"
)
WEEKLY_PREVIEW_MIRROR_URL = (
    "https://cdn.jsdelivr.net/gh/Murmansk-Seer/"
    "seer-unity-preview-img-dumper@main/img/preview.png"
)
_WEEKLY_PREVIEW_RAW_PREFIX = (
    "https://raw.githubusercontent.com/Murmansk-Seer/"
    "seer-unity-preview-img-dumper/main/"
)
_WEEKLY_PREVIEW_MIRROR_PREFIX = (
    "https://cdn.jsdelivr.net/gh/Murmansk-Seer/seer-unity-preview-img-dumper@main/"
)


def load_weekly_preview_metadata(session: Any) -> dict[str, str]:
    try:
        rows = session.execute(
            text(
                """
                SELECT key, value
                FROM seerapi_metadata
                WHERE key IN (:image_url_key, :image_urls_key, :source_url_key)
                """
            ),
            {
                "image_url_key": "weekly_preview_image_url",
                "image_urls_key": "weekly_preview_image_urls",
                "source_url_key": "weekly_preview_source_url",
            },
        ).all()
    except SQLAlchemyError:
        return {}

    return {str(row[0]): str(row[1]) for row in rows}


def load_weekly_preview_links(session: Any) -> tuple[tuple[str, ...], str]:
    metadata = load_weekly_preview_metadata(session)
    image_urls = _parse_image_urls(metadata.get("weekly_preview_image_urls", ""))
    image_url = (
        metadata.get("weekly_preview_image_url") or DEFAULT_WEEKLY_PREVIEW_IMAGE_URL
    )
    if not image_urls:
        image_urls = (
            DEFAULT_WEEKLY_PREVIEW_IMAGE_URLS
            if image_url == DEFAULT_WEEKLY_PREVIEW_IMAGE_URL
            else (image_url,)
        )
    source_url = (
        metadata.get("weekly_preview_source_url") or DEFAULT_WEEKLY_PREVIEW_SOURCE_URL
    )
    return image_urls, source_url


def weekly_preview_mirror_url(primary_url: str) -> str:
    if not primary_url.startswith(_WEEKLY_PREVIEW_RAW_PREFIX):
        return ""
    relative_path = primary_url.removeprefix(_WEEKLY_PREVIEW_RAW_PREFIX)
    return f"{_WEEKLY_PREVIEW_MIRROR_PREFIX}{relative_path}"


def _parse_image_urls(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in parsed if isinstance(item, str) and item.strip()
        )
    )
