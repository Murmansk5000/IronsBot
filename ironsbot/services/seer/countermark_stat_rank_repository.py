# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from seerapi_models import MintmarkORM
from seerapi_models.mintmark import AbilityPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from .value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from ironsbot.integrations.seer_data.sessions import SeerAPISession

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
            mintmark_id = coerce_positive_int(mapping["mintmark_id"])
            quality = coerce_positive_int(mapping["quality"])
        else:
            mintmark_id = coerce_positive_int(row[0])
            quality = coerce_positive_int(row[1])
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
