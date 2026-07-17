# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_WEEKLY_PREVIEW_IMAGE_URL = (
    "https://raw.githubusercontent.com/Murmansk-Seer/"
    "seer-unity-preview-img-dumper/main/img/preview.png"
)
DEFAULT_WEEKLY_PREVIEW_SOURCE_URL = (
    "https://github.com/Murmansk-Seer/seer-unity-preview-img-dumper"
)


def load_weekly_preview_metadata(session: Any) -> dict[str, str]:
    try:
        rows = session.execute(
            text(
                """
                SELECT key, value
                FROM ironsbot_metadata
                WHERE key IN (:image_url_key, :source_url_key)
                """
            ),
            {
                "image_url_key": "weekly_preview_image_url",
                "source_url_key": "weekly_preview_source_url",
            },
        ).all()
    except SQLAlchemyError:
        return {}

    return {str(row[0]): str(row[1]) for row in rows}


def load_weekly_preview_links(session: Any) -> tuple[str, str]:
    metadata = load_weekly_preview_metadata(session)
    image_url = (
        metadata.get("weekly_preview_image_url") or DEFAULT_WEEKLY_PREVIEW_IMAGE_URL
    )
    source_url = (
        metadata.get("weekly_preview_source_url") or DEFAULT_WEEKLY_PREVIEW_SOURCE_URL
    )
    return image_url, source_url
