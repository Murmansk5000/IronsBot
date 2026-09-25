# SPDX-License-Identifier: MIT
"""Read build-time SeerAPI facts needed by the pet information renderer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from sqlalchemy import text

from ironsbot.core.value_coercion import require_bool_flag
from ironsbot.services.seer.pet_info_views import (
    PetDerivedDisplayData,
    PetSoulmarkDisplayAddition,
    PetSpecialEffectView,
    SoulmarkIconAsset,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session


def load_pet_derived_display_data(
    session: Session,
    *,
    pet_id: int,
    soulmark_ids: Iterable[int],
) -> PetDerivedDisplayData:
    """Load facts emitted by the SeerAPI build without renderer-side inference."""
    effect_rows = _load_effect_rows(session, pet_id)
    source_rows = _load_effect_source_rows(session, pet_id)
    soulmark_display_order, soulmark_display_kinds = _load_soulmark_display_data(
        session,
        pet_id,
    )
    return PetDerivedDisplayData(
        special_effects=_build_effect_views(effect_rows, source_rows),
        soulmark_display_order=tuple(soulmark_display_order.items()),
        soulmark_icons=tuple(
            _load_soulmark_icons(session, pet_id, soulmark_ids).items()
        ),
        soulmark_display_additions=_load_soulmark_display_additions(session, pet_id),
        soulmark_display_kinds=tuple(soulmark_display_kinds.items()),
    )


def _load_effect_rows(session: Session, pet_id: int) -> list[dict[str, object]]:
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


def _load_effect_source_rows(
    session: Session,
    pet_id: int,
) -> dict[str, list[dict[str, object]]]:
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
                str(row["description"]) if row["description"] is not None else None
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


def _load_soulmark_display_data(
    session: Session,
    pet_id: int,
) -> tuple[dict[int, int], dict[int, str]]:
    rows = tuple(
        session.execute(
            text(
                """
                SELECT soulmark_id, display_order, display_kind
                FROM pet_soulmark_display
                WHERE pet_id = :pet_id
                ORDER BY display_order, soulmark_id
                """
            ),
            {"pet_id": pet_id},
        )
    )
    return (
        {int(row[0]): int(row[1]) for row in rows},
        {int(row[0]): str(row[2]) for row in rows},
    )


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
    rows = session.execute(
        text(
            f"""
            SELECT soulmark_id, icon_id, icon_png, icon_png_content_type
            FROM soulmark_icon
            WHERE pet_id = :pet_id
              AND soulmark_id IN ({placeholders})
            ORDER BY soulmark_id, icon_id
            """
        ),
        params,
    ).mappings()

    result: dict[int, SoulmarkIconAsset] = {}
    for row in rows:
        raw_png = row["icon_png"]
        png = (
            raw_png.tobytes() if isinstance(raw_png, memoryview) else bytes(raw_png)
        ) if raw_png is not None else None
        result[int(row["soulmark_id"])] = SoulmarkIconAsset(
            icon_id=int(row["icon_id"]),
            png=png,
            content_type=str(row["icon_png_content_type"] or "image/png"),
        )
    return result


def _load_soulmark_display_additions(
    session: Session,
    pet_id: int,
) -> tuple[PetSoulmarkDisplayAddition, ...]:
    """Load explicit build-time corrections without renderer-side pet branches."""
    rows = session.execute(
        text(
            """
            SELECT display_id, description, analyze_description,
                   formatting_adjustment, intensified, intensified_to_id,
                   is_adv, pve_effective, tags_json
            FROM pet_soulmark_display_addition
            WHERE pet_id = :pet_id
            ORDER BY display_order, display_id
            """
        ),
        {"pet_id": pet_id},
    ).mappings()
    return tuple(
        PetSoulmarkDisplayAddition(
            id=int(row["display_id"]),
            desc=str(row["description"]),
            analyze_desc=(
                str(row["analyze_description"])
                if row["analyze_description"] is not None
                else None
            ),
            formatting_adjustment=(
                str(row["formatting_adjustment"])
                if row["formatting_adjustment"] is not None
                else None
            ),
            intensified=require_bool_flag(
                row["intensified"], field="pet_soulmark_display_addition.intensified"
            ),
            intensified_to_id=(
                int(row["intensified_to_id"])
                if row["intensified_to_id"] is not None
                else None
            ),
            is_adv=require_bool_flag(
                row["is_adv"], field="pet_soulmark_display_addition.is_adv"
            ),
            pve_effective=(
                require_bool_flag(
                    row["pve_effective"],
                    field="pet_soulmark_display_addition.pve_effective",
                )
                if row["pve_effective"] is not None
                else None
            ),
            tags=_tags_from_json(row["tags_json"]),
        )
        for row in rows
    )


def _tags_from_json(value: object) -> tuple[str, ...]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or not all(isinstance(tag, str) for tag in parsed):
        raise TypeError("pet_soulmark_display_addition.tags_json")
    return tuple(parsed)
