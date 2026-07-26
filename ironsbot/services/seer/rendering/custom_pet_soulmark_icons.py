# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.images import SeerImageSource, to_data_uri

from .effect_icon_swf import EffectIconImage, effect_icon_swf_to_image

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.orm import Session

    from .custom_pet_models import SoulmarkDict

logger = logging.getLogger(__name__)

_EFFECT_ICON_ASSET_BASE_URL = "https://seer.61.com/resource/effectIcon"


def _apply_icon_row(soulmark: SoulmarkDict, row: RowMapping) -> None:
    soulmark["icon_id"] = int(row["icon_id"])
    png_data = row.get("icon_png")
    if png_data is not None:
        if isinstance(png_data, memoryview):
            png_data = png_data.tobytes()
        soulmark["icon"] = to_data_uri(
            bytes(png_data),
            mime_type=str(row.get("icon_png_content_type") or "image/png"),
        )
        return
    icon_asset_url = row.get("icon_asset_url")
    if icon_asset_url:
        soulmark["icon_asset_url"] = str(icon_asset_url)
        return
    icon_asset_status = row.get("icon_asset_status")
    if icon_asset_status is not None and int(icon_asset_status) == 0:
        soulmark["icon_asset_url"] = (
            f"{_EFFECT_ICON_ASSET_BASE_URL}/{soulmark['icon_id']}.swf"
        )


def resolve_soulmark_icon_urls(
    session: Session,
    soulmarks: Sequence[SoulmarkDict],
    *,
    pet_id: int,
) -> None:
    soulmark_ids = [soulmark["id"] for soulmark in soulmarks if soulmark["id"] > 0]
    if not soulmark_ids:
        return

    placeholders = ", ".join(f":id_{index}" for index, _ in enumerate(soulmark_ids))
    params: dict[str, int] = {"pet_id": pet_id}
    params.update(
        {
            f"id_{index}": soulmark_id
            for index, soulmark_id in enumerate(soulmark_ids)
        }
    )
    try:
        rows = session.execute(
            text(
                f"""
                SELECT
                    soulmark_id,
                    icon_id,
                    icon_asset_url,
                    icon_asset_status,
                    icon_png,
                    icon_png_content_type
                FROM soulmark_icon
                WHERE pet_id = :pet_id
                  AND soulmark_id IN ({placeholders})
                  AND (
                    (
                      icon_png_available = 1
                      AND icon_png IS NOT NULL
                    )
                    OR (
                      icon_asset_url IS NOT NULL
                      AND icon_asset_url != ''
                    )
                    OR icon_asset_status = 0
                  )
                """
            ),
            params,
        ).mappings()
    except SQLAlchemyError:
        try:
            rows = session.execute(
                text(
                    f"""
                    SELECT soulmark_id, icon_id, icon_asset_url
                    FROM soulmark_icon
                    WHERE pet_id = :pet_id
                      AND soulmark_id IN ({placeholders})
                      AND icon_asset_url IS NOT NULL
                      AND icon_asset_url != ''
                    """
                ),
                params,
            ).mappings()
        except SQLAlchemyError:
            return
    by_soulmark_id = {int(row["soulmark_id"]): row for row in rows}
    for soulmark in soulmarks:
        row = by_soulmark_id.get(soulmark["id"])
        if row is None:
            continue
        _apply_icon_row(soulmark, row)


async def load_soulmark_icons(
    images: SeerImageSource,
    soulmarks: Sequence[SoulmarkDict],
) -> None:
    icon_soulmarks = [
        soulmark
        for soulmark in soulmarks
        if soulmark["icon"] is None and soulmark["icon_asset_url"] is not None
    ]
    if not icon_soulmarks:
        return

    async def fetch_icon(soulmark: SoulmarkDict) -> EffectIconImage | None:
        try:
            swf_bytes = await images.fetch_url(str(soulmark["icon_asset_url"]))
            return effect_icon_swf_to_image(swf_bytes)
        except Exception as error:  # noqa: BLE001
            logger.debug(
                "failed to render soulmark icon: soulmark_id=%s icon_id=%s error=%s",
                soulmark["id"],
                soulmark["icon_id"],
                error,
            )
            return None

    results = await asyncio.gather(
        *(fetch_icon(soulmark) for soulmark in icon_soulmarks)
    )
    for soulmark, icon_image in zip(icon_soulmarks, results, strict=True):
        if icon_image is not None:
            soulmark["icon"] = to_data_uri(
                icon_image.data,
                mime_type=icon_image.mime_type,
            )
