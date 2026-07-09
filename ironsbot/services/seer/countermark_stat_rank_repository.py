# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from seerapi_models import MintmarkORM
from seerapi_models.mintmark import AbilityPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select

if TYPE_CHECKING:
    from ironsbot.integrations.seer_data.db import SeerAPISession

MINTMARK_QUALITY_QUERY = text("SELECT mintmark_id, quality FROM mintmark_quality")
MISSING_MINTMARK_QUALITY_MESSAGE = (
    "❌ 数据库缺少刻印角数表 mintmark_quality，请先更新 IronsBot 数据库。"
)

def load_mintmark_quality_session(session: SeerAPISession) -> dict[int, int]:
    try:
        rows = session.execute(MINTMARK_QUALITY_QUERY).all()
    except SQLAlchemyError:
        return {}

    quality_map: dict[int, int] = {}
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        if mapping is not None:
            mintmark_id = _coerce_quality(mapping["mintmark_id"])
            quality = _coerce_quality(mapping["quality"])
        else:
            mintmark_id = _coerce_quality(row[0])
            quality = _coerce_quality(row[1])
        if mintmark_id is not None and quality is not None:
            quality_map[mintmark_id] = quality
    return quality_map


def load_mintmarks(session: SeerAPISession) -> list[MintmarkORM]:
    statement = select(MintmarkORM).options(
        selectinload(cast("Any", MintmarkORM.ability_part)).selectinload(
            cast("Any", AbilityPartORM.max_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.skill_part)),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.base_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.max_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.extra_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.mintmark_class)
        ),
    )
    return list(session.exec(statement).all())

def _coerce_quality(value: object) -> int | None:
    try:
        quality = int(cast("Any", value))
    except (TypeError, ValueError):
        return None

    return quality if quality > 0 else None
