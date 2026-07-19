# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core.selection import (
    SelectionMenuItem,
    format_selection_menu,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess

AUTOCARD_PROMPT_MAX_ITEMS = 30
AUTOCARD_QUERY_PREFIXES = ("群星牌", "卡牌", "查询群星牌")
AUTOCARD_QUERY_SUFFIXES = ("群星牌",)

_AUTOCARD_NAME_STRIP_PATTERN = re.compile(r"[\s.·・•‧∙⋅。\-_/]+")
_AUTOCARD_MISSING_TABLE_MESSAGE = "数据库缺少群星牌表，请先更新 IronsBot 数据库。"
_AUTOCARD_EMPTY_DATA_MESSAGE = "数据库没有群星牌数据，请先更新 IronsBot 数据库。"
_CARD_TYPE_NAMES = {
    1: "精灵牌",
    2: "法术牌",
    3: "衍生精灵牌",
    4: "特殊牌",
}
_AUTOCARD_ASSET_BASE_URL = (
    "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
    "newseer/assets/art/autocard/texture"
)
_AUTOCARD_NON_PET_CARD_ID_START = 20000
_AUTOCARD_TABLE_QUERIES = {
    "autocard_card": text("SELECT raw_json FROM autocard_card ORDER BY id"),
    "autocard_role": text("SELECT raw_json FROM autocard_role ORDER BY id"),
    "autocard_nature": text("SELECT raw_json FROM autocard_nature ORDER BY id"),
}


@dataclass(slots=True, frozen=True)
class _AutocardDataset:
    cards: tuple[dict[str, Any], ...]
    roles: tuple[dict[str, Any], ...]
    natures: dict[int, str]


@dataclass(slots=True, frozen=True)
class AutocardPromptValue:
    kind: str
    item_id: int


@dataclass(slots=True, frozen=True)
class AutocardEntry:
    kind: str
    item_id: int
    name: str
    text: str
    image_url: str


@dataclass(slots=True, frozen=True)
class AutocardSearchResult:
    entry: AutocardEntry | None = None
    prompt_values: tuple[AutocardPromptValue, ...] = ()
    prompt_text: str = ""
    message: str = ""


class AutocardService:
    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def search(self, arg: str) -> AutocardSearchResult:
        with self._data.query(_load_autocard_dataset) as dataset:
            matches = _search_autocard_items(
                dataset,
                _extract_autocard_query_arg(arg),
            )
        if not matches:
            return AutocardSearchResult()
        if len(matches) == 1:
            kind, item = matches[0]
            return AutocardSearchResult(entry=_build_entry(dataset, kind, item))
        if len(matches) > AUTOCARD_PROMPT_MAX_ITEMS:
            return AutocardSearchResult(
                message=(
                    f"❌ 群星牌匹配超过 {AUTOCARD_PROMPT_MAX_ITEMS} 个，"
                    "请换更精确的关键词。"
                )
            )
        return AutocardSearchResult(
            prompt_values=_build_autocard_prompt_values(matches),
            prompt_text=_build_autocard_prompt_text(dataset, matches),
        )

    def select(self, value: AutocardPromptValue) -> AutocardEntry | None:
        with self._data.query(_load_autocard_dataset) as dataset:
            item = (
                _find_autocard_role_by_id(dataset, value.item_id)
                if value.kind == "role"
                else _find_autocard_card_by_id(dataset, value.item_id)
            )
        return (
            None
            if item is None
            else _build_entry(dataset, value.kind, item)
        )


def _extract_autocard_query_arg(arg: str) -> str:
    query = arg.strip()
    for prefix in AUTOCARD_QUERY_PREFIXES:
        if query.casefold().startswith(prefix.casefold()):
            query = query[len(prefix) :].strip()
            break

    for suffix in AUTOCARD_QUERY_SUFFIXES:
        if query.casefold().endswith(suffix.casefold()):
            query = query[: -len(suffix)].strip()
            break

    return query


def _load_autocard_dataset(session: Session) -> _AutocardDataset:
    try:
        cards = _load_json_rows(session, "autocard_card")
        roles = _load_json_rows(session, "autocard_role")
        nature_rows = _load_json_rows(session, "autocard_nature")
    except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(_AUTOCARD_MISSING_TABLE_MESSAGE) from e

    if not cards and not roles:
        raise RuntimeError(_AUTOCARD_EMPTY_DATA_MESSAGE)

    natures = {
        _int_field(row, "id"): str(_field(row, "name"))
        for row in nature_rows
    }
    return _AutocardDataset(
        cards=cards,
        roles=roles,
        natures=natures,
    )


def _find_autocard_card_by_id(
    dataset: _AutocardDataset,
    item_id: int,
) -> dict[str, Any] | None:
    for item in dataset.cards:
        if _int_field(item, "id") == item_id:
            return item
    return None


def _find_autocard_role_by_id(
    dataset: _AutocardDataset,
    item_id: int,
) -> dict[str, Any] | None:
    for item in dataset.roles:
        if _int_field(item, "id") == item_id:
            return item
    return None


def _search_autocard_items(
    dataset: _AutocardDataset,
    query: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = query.strip()
    if not query or query.isdigit():
        return []
    if query.startswith("卡") and query[1:].isdigit():
        card = _find_autocard_card_by_id(dataset, int(query[1:]))
        return [("card", card)] if card is not None else []

    normalized_query = _normalize_name(query)
    entries: list[tuple[str, dict[str, Any]]] = [
        ("card", card) for card in dataset.cards
    ] + [("role", role) for role in dataset.roles]
    exact = [
        (kind, item)
        for kind, item in entries
        if _normalize_name(_entry_name(item)) == normalized_query
    ]
    if exact:
        return exact

    return [
        (kind, item)
        for kind, item in entries
        if normalized_query in _normalize_name(_entry_name(item))
    ]


def _format_autocard_entry(
    dataset: _AutocardDataset,
    kind: str,
    item: dict[str, Any],
) -> str:
    if kind == "role":
        return _format_role(dataset, item)
    return _format_card(dataset, item)


def _autocard_image_url(kind: str, item: dict[str, Any]) -> str:
    image_name = _autocard_image_name(kind, item)
    if not image_name:
        return ""
    if kind == "role":
        return f"{_AUTOCARD_ASSET_BASE_URL}/roles/card/{image_name}.png"
    return f"{_AUTOCARD_ASSET_BASE_URL}/cards/{image_name}.png"


def _build_autocard_prompt_values(
    matches: list[tuple[str, dict[str, Any]]],
) -> tuple[AutocardPromptValue, ...]:
    return tuple(
        AutocardPromptValue(kind=kind, item_id=_int_field(item, "id"))
        for kind, item in matches
    )


def _build_autocard_prompt_text(
    dataset: _AutocardDataset,
    matches: list[tuple[str, dict[str, Any]]],
) -> str:
    return format_selection_menu(
        title="请问你想查询的群星牌资料是……",
        items=tuple(
            SelectionMenuItem(
                label=f"{_entry_name(item)}（{_prompt_desc(dataset, kind, item)}）"
            )
            for kind, item in matches
        ),
    )


def _normalize_name(value: object) -> str:
    return _AUTOCARD_NAME_STRIP_PATTERN.sub("", str(value)).casefold()


def _field(item: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in item:
            return item[name]
    return default


def _int_field(item: dict[str, Any], *names: str, default: int = 0) -> int:
    value = _field(item, *names, default=default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: object) -> str:
    return str(value).replace("\\n", "\n").strip()


def _load_json_rows(
    session: Session,
    table_name: str,
) -> tuple[dict[str, Any], ...]:
    query = _AUTOCARD_TABLE_QUERIES[table_name]
    rows = session.execute(query).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        raw_json = mapping["raw_json"] if mapping is not None else row[0]
        item = json.loads(str(raw_json))
        if isinstance(item, dict):
            result.append(item)
    return tuple(result)


def _entry_name(item: dict[str, Any]) -> str:
    return str(_field(item, "name", default=""))


def _card_variant(item: dict[str, Any]) -> str:
    return "金色" if _int_field(item, "compose") else "普通"


def _autocard_image_name(kind: str, item: dict[str, Any]) -> str:
    if kind == "role":
        pic_id = _int_field(item, "picID", "pic_id")
        return f"role_{pic_id}" if pic_id > 0 else ""

    item_id = _int_field(item, "id")
    pic_id = _int_field(item, "picID", "pic_id")
    image_id = (
        pic_id
        if item_id < _AUTOCARD_NON_PET_CARD_ID_START and pic_id > 0
        else item_id
    )
    return f"card_{image_id}" if image_id > 0 else ""


def _nature_name(dataset: _AutocardDataset, nature_id: int) -> str:
    if nature_id <= 0:
        return "无"
    return dataset.natures.get(nature_id, f"属性{nature_id}")


def _format_card(dataset: _AutocardDataset, item: dict[str, Any]) -> str:
    item_id = _int_field(item, "id")
    type_id = _int_field(item, "type")
    nature_id = _int_field(item, "nature")
    attack = _int_field(item, "attack")
    health = _int_field(item, "health")
    card_text = _clean_text(_field(item, "cardTxt", "card_txt", default=""))
    desc = _clean_text(_field(item, "des", default=""))

    lines = [
        "🃏【群星牌】",
        f"{_entry_name(item)}（ID：{item_id}，{_card_variant(item)}）",
        (
            f"类型：{_CARD_TYPE_NAMES.get(type_id, f'类型{type_id}')}"
            f" | 属性：{_nature_name(dataset, nature_id)}"
            f" | 等级：{_int_field(item, 'level')}"
            f" | 费用：{_int_field(item, 'cost')}"
        ),
    ]
    if attack or health:
        lines.append(f"身材：{attack}/{health}")
    if card_text:
        lines.append(f"效果：{card_text}")
    if desc:
        lines.append(f"描述：{desc}")

    return "\n".join(lines)


def _format_role(dataset: _AutocardDataset, item: dict[str, Any]) -> str:
    item_id = _int_field(item, "id")
    nature_id = _int_field(item, "nature")
    skill_name = _clean_text(_field(item, "skillName", "skill_name", default=""))
    skill_text = _clean_text(_field(item, "skillTxt", "skill_txt", default=""))
    skill_upgrade = _clean_text(
        _field(item, "skillUpgrade", "skill_upgrade", default="")
    )
    desc = _clean_text(_field(item, "desc", default=""))

    lines = [
        "🧑‍🚀【群星牌角色】",
        f"{_entry_name(item)}（ID：{item_id}）",
        (
            f"属性：{_nature_name(dataset, nature_id)}"
            f" | 生命：{_int_field(item, 'health')}"
        ),
    ]
    if skill_name:
        lines.append(f"技能：{skill_name}")
    if skill_text:
        lines.append(f"效果：{skill_text}")
    if skill_upgrade:
        lines.append(f"升级：{skill_upgrade}")
    if desc:
        lines.append(f"描述：{desc}")

    return "\n".join(lines)


def _prompt_desc(dataset: _AutocardDataset, kind: str, item: dict[str, Any]) -> str:
    item_id = _int_field(item, "id")
    if kind == "role":
        nature = _nature_name(dataset, _int_field(item, "nature"))
        return f"角色 {item_id} {nature}"

    nature = _nature_name(dataset, _int_field(item, "nature"))
    type_name = _CARD_TYPE_NAMES.get(_int_field(item, "type"), "卡牌")
    return (
        f"{type_name} {item_id} {_card_variant(item)} "
        f"Lv{_int_field(item, 'level')} {nature}"
    )


def _build_entry(
    dataset: _AutocardDataset,
    kind: str,
    item: dict[str, Any],
) -> AutocardEntry:
    return AutocardEntry(
        kind=kind,
        item_id=_int_field(item, "id"),
        name=_entry_name(item),
        text=_format_autocard_entry(dataset, kind, item),
        image_url=_autocard_image_url(kind, item),
    )
