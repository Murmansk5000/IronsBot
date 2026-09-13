# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the published autocard tables into one query-ready dataset."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core.value_coercion import require_int
from ironsbot.services.seer.autocard import AutocardDataset

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader

_MISSING_TABLE_MESSAGE = "数据库缺少群星牌表，请先更新 IronsBot 数据库。"
_EMPTY_DATA_MESSAGE = "数据库没有群星牌数据，请先更新 IronsBot 数据库。"
_INVALID_DATA_MESSAGE = "数据库中的群星牌数据格式无效，请更新 IronsBot 数据库。"
_CARD_INTEGER_FIELDS = (
    "id",
    "type",
    "nature",
    "level",
    "cost",
    "attack",
    "health",
    "compose",
    "composeTo",
    "picID",
)
_JSON_TABLE_QUERIES = {
    "autocard_card": text("SELECT raw_json FROM autocard_card ORDER BY id"),
    "autocard_nature": text("SELECT raw_json FROM autocard_nature ORDER BY id"),
}
_ROLE_QUERY = text(
    """
    SELECT
        role.id,
        role.name,
        role.description,
        role.health,
        role.skill_desc,
        role.element_type_id,
        raw.pic_id,
        raw.skill_id,
        raw.skill_name,
        raw.skill_upgrade,
        raw.raw_json
    FROM autocard_role AS role
    JOIN autocard_role_raw AS raw ON raw.role_id = role.id
    ORDER BY role.id
    """
)


class PublishedAutocardRepository:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def load(self) -> AutocardDataset:
        with self._data.query(load_autocard_dataset) as dataset:
            return dataset


def load_autocard_dataset(session: Session) -> AutocardDataset:
    """Load only the current SeerAPI autocard schema."""

    try:
        cards = _load_json_rows(session, "autocard_card")
        roles = _load_role_rows(session)
        nature_rows = _load_json_rows(session, "autocard_nature")
    except SQLAlchemyError as error:
        raise RuntimeError(_MISSING_TABLE_MESSAGE) from error
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(_INVALID_DATA_MESSAGE) from error
    if not cards and not roles:
        raise RuntimeError(_EMPTY_DATA_MESSAGE)
    return AutocardDataset(
        cards=cards,
        roles=roles,
        natures={
            require_int(row.get("id"), field="autocard_nature.id"): str(
                row.get("name") or ""
            )
            for row in nature_rows
        },
    )


def _load_json_rows(
    session: Session,
    table_name: str,
) -> tuple[dict[str, Any], ...]:
    rows = session.execute(_JSON_TABLE_QUERIES[table_name]).all()
    values: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        item = json.loads(str(mapping["raw_json"] if mapping is not None else row[0]))
        if not isinstance(item, dict):
            raise TypeError(table_name)
        if table_name == "autocard_card":
            for field in _CARD_INTEGER_FIELDS:
                item[field] = require_int(
                    item.get(field, 0),
                    field=f"autocard_card.{field}",
                )
        values.append(item)
    return tuple(values)


def _load_role_rows(session: Session) -> tuple[dict[str, Any], ...]:
    values: list[dict[str, Any]] = []
    for row in session.execute(_ROLE_QUERY).all():
        mapping = row._mapping if hasattr(row, "_mapping") else None
        columns = (
            mapping
            if mapping is not None
            else {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "health": row[3],
                "skill_desc": row[4],
                "element_type_id": row[5],
                "pic_id": row[6],
                "skill_id": row[7],
                "skill_name": row[8],
                "skill_upgrade": row[9],
                "raw_json": row[10],
            }
        )
        item = json.loads(str(columns["raw_json"]))
        if not isinstance(item, dict):
            raise TypeError("autocard_role_raw")
        item.update(
            {
                "id": require_int(columns["id"], field="autocard_role.id"),
                "name": str(columns["name"]),
                "desc": str(columns["description"]),
                "health": require_int(columns["health"], field="autocard_role.health"),
                "skillTxt": str(columns["skill_desc"]),
                "nature": require_int(
                    columns["element_type_id"], field="autocard_role.element_type_id"
                ),
                "picID": require_int(
                    columns["pic_id"], field="autocard_role_raw.pic_id"
                ),
                "skillID": require_int(
                    columns["skill_id"], field="autocard_role_raw.skill_id"
                ),
                "skillName": str(columns["skill_name"]),
                "skillUpgrade": str(columns["skill_upgrade"]),
            }
        )
        values.append(item)
    return tuple(values)
