# SPDX-License-Identifier: GPL-3.0-or-later
"""Read published autocard sanctuary effects without leaking SQL into services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core.value_coercion import require_int

if TYPE_CHECKING:
    from sqlmodel import Session

_MISSING_TABLE_MESSAGE = "数据库缺少群星牌场地效果表，请先更新 IronsBot 数据库。"
_EMPTY_DATA_MESSAGE = "数据库没有群星牌场地效果数据，请先更新 IronsBot 数据库。"
_INVALID_DATA_MESSAGE = (
    "数据库中的群星牌场地效果数据格式无效，请更新 IronsBot 数据库。"
)
_EFFECT_QUERY = text(
    """
    SELECT
        effect.id AS effect_id,
        effect.sanctuary_id,
        effect.name AS effect_name,
        effect.description,
        effect.unlock_round,
        effect.stage,
        base.name AS sanctuary_name,
        base.pic_id AS sanctuary_pet_id,
        pet.name AS sanctuary_pet_name
    FROM autocard_season_effect AS effect
    LEFT JOIN autocard_season_effect AS base
      ON base.sanctuary_id = effect.sanctuary_id
     AND base.unlock_round = 0
    LEFT JOIN pet ON pet.id = base.pic_id
    ORDER BY effect.sanctuary_id, effect.unlock_round, effect.id
    """
)


@dataclass(frozen=True, slots=True)
class AutocardSanctuaryRow:
    effect_id: int
    sanctuary_id: int
    effect_name: str
    description: str
    unlock_round: int
    stage: int
    sanctuary_name: str
    sanctuary_pet_id: int
    sanctuary_pet_name: str


def load_autocard_sanctuary_rows(
    session: Session,
) -> tuple[AutocardSanctuaryRow, ...]:
    """Load the current autocard sanctuary schema."""

    try:
        rows = session.execute(_EFFECT_QUERY).all()
    except SQLAlchemyError as error:
        raise RuntimeError(_MISSING_TABLE_MESSAGE) from error
    if not rows:
        raise RuntimeError(_EMPTY_DATA_MESSAGE)
    try:
        return tuple(_row_to_record(row) for row in rows)
    except (TypeError, ValueError) as error:
        raise RuntimeError(_INVALID_DATA_MESSAGE) from error


def _row_to_record(row: object) -> AutocardSanctuaryRow:
    return AutocardSanctuaryRow(
        effect_id=_as_int(_value(row, "effect_id", 0)),
        sanctuary_id=_as_int(_value(row, "sanctuary_id", 1)),
        effect_name=_as_text(_value(row, "effect_name", 2)),
        description=_as_text(_value(row, "description", 3)),
        unlock_round=_as_int(_value(row, "unlock_round", 4)),
        stage=_as_int(_value(row, "stage", 5)),
        sanctuary_name=_as_text(_value(row, "sanctuary_name", 6)),
        sanctuary_pet_id=_as_int(_value(row, "sanctuary_pet_id", 7)),
        sanctuary_pet_name=_as_text(_value(row, "sanctuary_pet_name", 8)),
    )


def _value(row: object, name: str, index: int) -> object:
    mapping = getattr(row, "_mapping", None)
    return mapping[name] if mapping is not None else row[index]  # type: ignore[index]


def _as_int(value: object) -> int:
    return require_int(value, field="autocard_sanctuary")


def _as_text(value: object) -> str:
    return str(value or "").replace("\\n", "\n").strip()
