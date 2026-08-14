# SPDX-License-Identifier: MIT
"""Read the release-level new-content index embedded by seerapi."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess


NewContentCategory = Literal[
    "achievement",
    "pet",
    "peak_pool",
    "pet_skin",
    "skill",
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
    "peak_pool",
    "pet_skin",
    "skill",
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
    "peak_pool": "竞技池变化",
    "pet_skin": "新增皮肤",
    "skill": "新增技能",
    "mintmark": "新增刻印",
    "suit": "新增套装",
    "equip": "新增部件",
    "mount": "新增座驾",
    "autocard_card": "新增群星牌",
    "autocard_role": "新增群星牌角色",
    "autocard_sanctuary_effect": "新增群星牌圣域",
}
_CONFIG_VERSION_DATE_LENGTH = 8
_CONFIG_VERSION_TIMESTAMP_LENGTH = 14
DEFAULT_NEW_CONTENT_AUTO_EXPAND_MAX_ITEMS = 5


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


def is_new_content_category_auto_expanded(
    snapshot: NewContentSnapshot,
    category: NewContentCategory,
    max_items: int,
) -> bool:
    """Expand short root-menu categories; zero disables automatic expansion."""

    item_count = len(snapshot.items_for(category))
    return 0 < item_count <= max_items


def format_new_content_category_count(
    items: tuple[NewContentItem, ...],
) -> str:
    """Show additions and corrections separately in weekly category menus."""

    added = sum(item.change_kind == "added" for item in items)
    modified = sum(item.change_kind == "modified" for item in items)
    parts = []
    if added:
        parts.append(f"{added} 项新增")
    if modified:
        parts.append(f"{modified} 项修改")
    return "｜".join(parts) or "0 项"


class NewContentService:
    """Read-only access to the publication index; no local baseline is kept."""

    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def snapshot(self) -> NewContentSnapshot:
        with self._data.query(_load_snapshot) as snapshot:
            return snapshot


def format_new_content_item_description(item: NewContentItem) -> str:  # noqa: PLR0911
    """Keep text and rendered new-content menus on the same item wording."""

    change = "修改" if item.change_kind == "modified" else "新增"
    if item.category == "achievement":
        point = int(item.payload.get("point", 0))
        titles = item.payload.get("titles", [])
        title_text = f"｜称号：{titles[0].get('name', '')}" if titles else ""
        return f"{change}｜{item.entity_id}｜{point} 点{title_text}"
    if item.category == "pet_skin":
        pet_name = str(item.payload.get("pet_name", ""))
        return f"{change}｜{item.entity_id}｜{pet_name or '未关联精灵'}"
    if item.category == "peak_pool":
        previous_limit = _format_peak_pool_limit(item.payload.get("previous_limit"))
        current_limit = _format_peak_pool_limit(item.payload.get("current_limit"))
        return f"修改｜{item.entity_id}｜{previous_limit} → {current_limit}"
    if item.category == "skill":
        pets = item.payload.get("pets", [])
        names = (
            "、".join(
                str(pet.get("name", "")).strip()
                for pet in pets
                if isinstance(pet, dict) and str(pet.get("name", "")).strip()
            )
            if isinstance(pets, list)
            else ""
        )
        return f"{change}｜{item.entity_id}{f'｜{names}' if names else ''}"
    if item.category in {"autocard_card", "autocard_role"}:
        kind = "角色" if item.category == "autocard_role" else "卡牌"
        return f"{change}｜{item.entity_id}｜{kind}"
    if item.category == "autocard_sanctuary_effect":
        sanctuary = str(item.payload.get("sanctuary_name", "")).strip()
        sanctuary = sanctuary or f"圣域 {int(item.payload.get('sanctuary_id', 0))}"
        pet_name = str(item.payload.get("sanctuary_pet_name", "")).strip()
        pet = f"｜精灵王：{pet_name}" if pet_name else ""
        unlock_round = int(item.payload.get("unlock_round", 0))
        phase = "基础圣域" if unlock_round == 0 else f"第 {unlock_round} 回合祝印"
        return f"{change}｜{sanctuary}{pet}｜{phase}"
    return f"{change}｜{item.entity_id}"


def _format_peak_pool_limit(value: object) -> str:
    if value is None:
        return "不限"
    try:
        return f"限{int(value)}"
    except (TypeError, ValueError):
        return "未知"


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
        weekly_cycle=_current_content_date(
            str(release["current_config_version"]),
            str(release["weekly_cycle"]),
        ),
        items=tuple(items),
        category_states=tuple(category_states),
    )


def _current_content_date(config_version: str, fallback: str) -> str:
    """Show the current release date, not the older comparison baseline date."""

    try:
        if (
            len(config_version) == _CONFIG_VERSION_TIMESTAMP_LENGTH
            and config_version.isdigit()
        ):
            return (
                datetime.strptime(config_version, "%Y%m%d%H%M%S")
                .replace(tzinfo=timezone.utc)
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .date()
                .isoformat()
            )
        if (
            len(config_version) == _CONFIG_VERSION_DATE_LENGTH
            and config_version.isdigit()
        ):
            return (
                datetime.strptime(config_version, "%Y%m%d")
                .replace(tzinfo=timezone.utc)
                .date()
                .isoformat()
            )
    except ValueError:
        pass
    return fallback


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
