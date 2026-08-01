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
    "autocard_sanctuary_effect",
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
    "autocard_sanctuary_effect",
)

# "新增群星牌" is the umbrella view for all weekly Autocard changes.  The
# individual categories remain available for the general new-content menu and
# their focused commands.
AUTOCARD_NEW_CONTENT_CATEGORIES: tuple[NewContentCategory, ...] = (
    "autocard_card",
    "autocard_role",
    "autocard_sanctuary_effect",
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
    "autocard_sanctuary_effect": "新增群星牌圣域",
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
class NewContentCategoryState:
    """Whether a category has a comparable source snapshot this week."""

    category: NewContentCategory
    comparison_ready: bool
    reason: str


@dataclass(frozen=True, slots=True)
class NewContentSnapshot:
    baseline_established: bool
    config_version: str
    weekly_cycle: str
    items: tuple[NewContentItem, ...]
    category_states: tuple[NewContentCategoryState, ...] = ()

    def items_for(self, category: NewContentCategory) -> tuple[NewContentItem, ...]:
        return tuple(item for item in self.items if item.category == category)

    def category_state(self, category: NewContentCategory) -> NewContentCategoryState:
        for state in self.category_states:
            if state.category == category:
                return state
        # Older releases do not carry per-category state. Their index is still
        # trustworthy when its legacy global baseline was completed.
        return NewContentCategoryState(
            category=category,
            comparison_ready=self.baseline_established,
            reason=(
                "legacy_index"
                if self.baseline_established
                else "history_unavailable"
            ),
        )

    def is_category_comparable(self, category: NewContentCategory) -> bool:
        return self.category_state(category).comparison_ready


class NewContentService:
    """Read-only access to the publication index; no local baseline is kept."""

    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def snapshot(self) -> NewContentSnapshot:
        with self._data.query(_load_snapshot) as snapshot:
            return snapshot


def _load_snapshot(session: Session) -> NewContentSnapshot:
    try:
        connection = session.connection()
        release = (
            connection
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
            connection
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
        state_rows = ()
        has_category_state = connection.exec_driver_sql(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'new_content_category_state'
            """
        ).first()
        if has_category_state:
            state_rows = (
                connection
                .exec_driver_sql(
                    """
                    SELECT category, comparison_ready, reason
                    FROM new_content_category_state
                    ORDER BY category
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
    category_states: list[NewContentCategoryState] = []
    for row in state_rows:
        category = str(row["category"])
        if category not in NEW_CONTENT_CATEGORIES:
            continue
        category_states.append(
            NewContentCategoryState(
                category=category,  # type: ignore[arg-type]
                comparison_ready=bool(row["comparison_ready"]),
                reason=str(row["reason"]),
            )
        )
    return NewContentSnapshot(
        baseline_established=bool(release["baseline_established"]),
        config_version=str(release["current_config_version"]),
        weekly_cycle=str(release["weekly_cycle"]),
        items=tuple(items),
        category_states=tuple(category_states),
    )


def new_content_unavailable_message() -> str:
    return "当前数据版本尚未提供新增内容记录。"


def new_content_category_unavailable_message(
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
) -> str:
    names = "、".join(CATEGORY_NAMES[category] for category in categories)
    states = tuple(snapshot.category_state(category) for category in categories)
    if all(state.reason == "first_observation" for state in states):
        return f"{names}已开始记录，当前暂无可比较的历史数据。"
    if all(state.reason == "source_unavailable" for state in states):
        return f"当前数据版本未提供{names}数据。"
    return f"当前暂无可验证的{names}新增或修改内容。"
