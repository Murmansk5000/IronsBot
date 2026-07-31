# SPDX-License-Identifier: MIT
"""Read the release-level new-content index embedded by seerapi."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess


NewContentCategory = Literal[
    "achievement",
    "pet",
    "pet_skin",
    "mintmark",
    "suit",
    "equip",
    "mount",
    "autocard_card",
    "autocard_role",
]

NEW_CONTENT_CATEGORIES: tuple[NewContentCategory, ...] = (
    "pet",
    "pet_skin",
    "mintmark",
    "suit",
    "equip",
    "mount",
    "achievement",
    "autocard_card",
    "autocard_role",
)

CATEGORY_NAMES: dict[NewContentCategory, str] = {
    "achievement": "新增成就",
    "pet": "新增精灵",
    "pet_skin": "新增皮肤",
    "mintmark": "新增刻印",
    "suit": "新增套装",
    "equip": "新增部件",
    "mount": "新增座驾",
    "autocard_card": "新增群星牌",
    "autocard_role": "新增群星牌角色",
}


class NewContentIndexUnavailableError(RuntimeError):
    """The downloaded SeerAPI release predates the embedded index."""


@dataclass(frozen=True, slots=True)
class NewContentItem:
    category: NewContentCategory
    entity_id: int
    name: str
    sort_value: int
    payload: dict[str, Any]
    change_kind: Literal["added", "modified"] = "added"


@dataclass(frozen=True, slots=True)
class NewContentSnapshot:
    baseline_established: bool
    config_version: str
    weekly_cycle: str
    items: tuple[NewContentItem, ...]

    def items_for(self, category: NewContentCategory) -> tuple[NewContentItem, ...]:
        return tuple(item for item in self.items if item.category == category)


class NewContentService:
    """Read-only access to the publication index; no local baseline is kept."""

    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def snapshot(self) -> NewContentSnapshot:
        with self._data.query(_load_snapshot) as snapshot:
            return snapshot


def _load_snapshot(session: Session) -> NewContentSnapshot:
    try:
        release = (
            session.connection()
            .exec_driver_sql(
                """
            SELECT current_config_version, weekly_cycle, baseline_established
            FROM new_content_release
            WHERE id = 1
            """
            )
            .mappings()
            .first()
        )
        if release is None:
            raise NewContentIndexUnavailableError
        rows = (
            session.connection()
            .exec_driver_sql(
                """
            SELECT category, entity_id, name, sort_value, payload_json, change_kind
            FROM new_content_item
            ORDER BY category, sort_value, entity_id
            """
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError as error:
        raise NewContentIndexUnavailableError from error

    items: list[NewContentItem] = []
    for row in rows:
        category = str(row["category"])
        if category not in NEW_CONTENT_CATEGORIES:
            continue
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            payload = {}
        items.append(
            NewContentItem(
                category=category,  # type: ignore[arg-type]
                entity_id=int(row["entity_id"]),
                name=str(row["name"]),
                sort_value=int(row["sort_value"]),
                payload=payload if isinstance(payload, dict) else {},
                change_kind=(
                    "modified" if str(row["change_kind"]) == "modified" else "added"
                ),
            )
        )
    return NewContentSnapshot(
        baseline_established=bool(release["baseline_established"]),
        config_version=str(release["current_config_version"]),
        weekly_cycle=str(release["weekly_cycle"]),
        items=tuple(items),
    )


def new_content_unavailable_message(snapshot: NewContentSnapshot | None = None) -> str:
    if snapshot is not None and not snapshot.baseline_established:
        return "当前数据版本仅建立了新增内容对比基线，请等待下一次官方数据更新。"
    return "当前数据版本尚未提供新增内容记录。"
