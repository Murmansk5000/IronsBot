# SPDX-License-Identifier: MIT
"""Read build-time SeerAPI facts needed by the pet information renderer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.rendering.pet_effect_presentation import (
    PetDerivedDisplayData,
    PetSpecialEffectView,
    SoulmarkIconAsset,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def load_pet_derived_display_data(
    session: Session,
    *,
    pet_id: int,
    soulmark_ids: Iterable[int],
) -> PetDerivedDisplayData:
    """Load facts emitted by the SeerAPI build without renderer-side inference."""
    effect_rows = _load_effect_rows(session, pet_id)
    source_rows = _load_effect_source_rows(session, pet_id)
    return PetDerivedDisplayData(
        special_effects=_build_effect_views(effect_rows, source_rows),
        soulmark_display_order=_load_soulmark_display_order(session, pet_id),
        soulmark_icons=_load_soulmark_icons(session, pet_id, soulmark_ids),
    )


def _load_effect_rows(session: Session, pet_id: int) -> list[dict[str, object]]:
    try:
        return [
            dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT effect_key, glossary_id, status_id, name, description
                    FROM pet_special_effect
                    WHERE pet_id = :pet_id
                    ORDER BY sort_id IS NULL, sort_id, effect_key
                    """
                ),
                {"pet_id": pet_id},
            ).mappings()
        ]
    except SQLAlchemyError:
        logger.debug("pet special-effect facts are unavailable", exc_info=True)
        return []


def _load_effect_source_rows(
    session: Session,
    pet_id: int,
) -> dict[str, list[dict[str, object]]]:
    try:
        rows = session.execute(
            text(
                """
                SELECT effect_key, source_kind, source_id, resolution_rule,
                       source_detail
                FROM pet_special_effect_source
                WHERE pet_id = :pet_id
                ORDER BY effect_key, source_kind, source_id, resolution_rule
                """
            ),
            {"pet_id": pet_id},
        ).mappings()
    except SQLAlchemyError:
        logger.debug("pet special-effect sources are unavailable", exc_info=True)
        return {}

    result: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        result.setdefault(str(row["effect_key"]), []).append(dict(row))
    return result


def _build_effect_views(
    effect_rows: Iterable[dict[str, object]],
    source_rows: dict[str, list[dict[str, object]]],
) -> tuple[PetSpecialEffectView, ...]:
    return tuple(
        PetSpecialEffectView(
            name=str(row["name"]),
            description=(
                str(row["description"])
                if row["description"] is not None
                else None
            ),
            glossary_id=(
                int(cast("int", row["glossary_id"]))
                if row["glossary_id"] is not None
                else None
            ),
            status_id=(
                int(cast("int", row["status_id"]))
                if row["status_id"] is not None
                else None
            ),
            sources=tuple(
                dict.fromkeys(
                    _format_effect_source(source)
                    for source in source_rows.get(str(row["effect_key"]), [])
                )
            ),
        )
        for row in effect_rows
    )


def _format_effect_source(source: dict[str, object]) -> str:
    kind = str(source["source_kind"])
    source_id = int(cast("int", source["source_id"]))
    detail = str(source.get("source_detail") or "").strip()
    if kind == "skill":
        return f"技能·{detail}" if detail else f"技能 {source_id}"
    if kind == "soulmark":
        return f"魂印状态{source_id}"
    return {
        "pet_glossary": "官方关联词条",
        "glossary_link": "官方词条关联",
        "status": "官方状态关联",
        "glossary": "官方词条",
    }.get(kind, kind)


def _load_soulmark_display_order(session: Session, pet_id: int) -> dict[int, int]:
    try:
        rows = session.execute(
            text(
                """
                SELECT soulmark_id, display_order
                FROM pet_soulmark_display
                WHERE pet_id = :pet_id
                ORDER BY display_order, soulmark_id
                """
            ),
            {"pet_id": pet_id},
        )
    except SQLAlchemyError:
        logger.debug("pet soulmark display facts are unavailable", exc_info=True)
        return {}
    return {int(soulmark_id): int(display_order) for soulmark_id, display_order in rows}


def _load_soulmark_icons(
    session: Session,
    pet_id: int,
    soulmark_ids: Iterable[int],
) -> dict[int, SoulmarkIconAsset]:
    ids = tuple(
        dict.fromkeys(soulmark_id for soulmark_id in soulmark_ids if soulmark_id > 0)
    )
    if not ids:
        return {}
    placeholders = ", ".join(f":soulmark_{index}" for index, _ in enumerate(ids))
    params: dict[str, int] = {"pet_id": pet_id}
    params.update(
        {f"soulmark_{index}": soulmark_id for index, soulmark_id in enumerate(ids)}
    )
    try:
        rows = session.execute(
            text(
                f"""
                SELECT soulmark_id, icon_id, icon_png, icon_png_content_type
                FROM soulmark_icon
                WHERE pet_id = :pet_id
                  AND soulmark_id IN ({placeholders})
                  AND icon_png_available = 1
                  AND icon_png IS NOT NULL
                ORDER BY soulmark_id, icon_id
                """
            ),
            params,
        ).mappings()
    except SQLAlchemyError:
        logger.debug("pre-rendered soulmark icon facts are unavailable", exc_info=True)
        return {}

    result: dict[int, SoulmarkIconAsset] = {}
    for row in rows:
        raw_png = row["icon_png"]
        png = raw_png.tobytes() if isinstance(raw_png, memoryview) else bytes(raw_png)
        result[int(row["soulmark_id"])] = SoulmarkIconAsset(
            icon_id=int(row["icon_id"]),
            png=png,
            content_type=str(row["icon_png_content_type"] or "image/png"),
        )
    return result
