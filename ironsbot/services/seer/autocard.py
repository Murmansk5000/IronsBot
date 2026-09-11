# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import logging
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
    "autocard_nature": text("SELECT raw_json FROM autocard_nature ORDER BY id"),
}
_AUTOCARD_ROLE_QUERY = text(
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
_LEGACY_AUTOCARD_ROLE_QUERY = text("SELECT raw_json FROM autocard_role ORDER BY id")
logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _AutocardDataset:
    cards: tuple[dict[str, Any], ...]
    roles: tuple[dict[str, Any], ...]
    natures: dict[int, str]
    cards_by_id: dict[int, dict[str, Any]]
    card_pair_base_ids: dict[int, int]
    awakened_ids_by_base_id: dict[int, int]


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
    description: str = ""
    skill_name: str = ""
    skill_text: str = ""
    skill_upgrade: str = ""
    additional_image_urls: tuple[str, ...] = ()

    @property
    def image_urls(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                url for url in (self.image_url, *self.additional_image_urls) if url
            )
        )


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
            if value.kind == "role":
                item = _find_autocard_role_by_id(dataset, value.item_id)
            else:
                item = _find_autocard_card_by_id(dataset, value.item_id)
        return None if item is None else _build_entry(dataset, value.kind, item)


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
        roles = _load_role_rows(session)
        nature_rows = _load_json_rows(session, "autocard_nature")
    except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(_AUTOCARD_MISSING_TABLE_MESSAGE) from e

    if not cards and not roles:
        raise RuntimeError(_AUTOCARD_EMPTY_DATA_MESSAGE)

    natures = {_int_field(row, "id"): str(_field(row, "name")) for row in nature_rows}
    cards_by_id = {_int_field(card, "id"): card for card in cards}
    card_pair_base_ids, awakened_ids_by_base_id = _index_card_pairs(cards_by_id)
    return _AutocardDataset(
        cards=cards,
        roles=roles,
        natures=natures,
        cards_by_id=cards_by_id,
        card_pair_base_ids=card_pair_base_ids,
        awakened_ids_by_base_id=awakened_ids_by_base_id,
    )


def _index_card_pairs(
    cards_by_id: dict[int, dict[str, Any]],
) -> tuple[dict[int, int], dict[int, int]]:
    base_ids: dict[int, int] = {}
    awakened_ids: dict[int, int] = {}
    for base_id, card in cards_by_id.items():
        target_id = _int_field(card, "composeTo")
        if _int_field(card, "compose") != 0 or target_id <= 0:
            continue
        target = cards_by_id.get(target_id)
        if target is None or _int_field(target, "compose") != 1:
            logger.warning(
                "invalid autocard compose relation: base_id=%s target_id=%s",
                base_id,
                target_id,
            )
            continue
        existing_base_id = base_ids.get(target_id)
        if existing_base_id is not None:
            logger.warning(
                "duplicate autocard compose target: target_id=%s base_ids=%s,%s",
                target_id,
                existing_base_id,
                base_id,
            )
            continue
        base_ids[base_id] = base_id
        base_ids[target_id] = base_id
        awakened_ids[base_id] = target_id
    return base_ids, awakened_ids


def _find_autocard_card_by_id(
    dataset: _AutocardDataset,
    item_id: int,
) -> dict[str, Any] | None:
    return dataset.cards_by_id.get(item_id)


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
        if card is None:
            return []
        base, awakened = _card_pair(dataset, card)
        return [("card_group" if awakened is not None else "card", base)]

    normalized_query = _normalize_name(query)
    entries = _grouped_card_search_entries(dataset) + [
        ("role", role) for role in dataset.roles
    ]
    exact = [
        (kind, item)
        for kind, item in entries
        if normalized_query in _entry_search_names(dataset, kind, item)
    ]
    if exact:
        return exact

    return [
        (kind, item)
        for kind, item in entries
        if any(
            normalized_query in name
            for name in _entry_search_names(dataset, kind, item)
        )
    ]


def _entry_search_names(
    dataset: _AutocardDataset,
    kind: str,
    item: dict[str, Any],
) -> tuple[str, ...]:
    names = [_normalize_name(_entry_name(item))]
    if kind == "card_group":
        _base, awakened = _card_pair(dataset, item)
        if awakened is not None:
            names.append(_normalize_name(_entry_name(awakened)))
    return tuple(dict.fromkeys(names))


def _grouped_card_search_entries(
    dataset: _AutocardDataset,
) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    consumed_ids: set[int] = set()
    for card in dataset.cards:
        item_id = _int_field(card, "id")
        if item_id in consumed_ids:
            continue
        base, awakened = _card_pair(dataset, card)
        consumed_ids.add(_int_field(base, "id"))
        if awakened is not None:
            consumed_ids.add(_int_field(awakened, "id"))
        entries.append(("card_group" if awakened is not None else "card", base))
    return entries


def _card_pair(
    dataset: _AutocardDataset,
    item: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    item_id = _int_field(item, "id")
    base_id = dataset.card_pair_base_ids.get(item_id)
    if base_id is None:
        return item, None
    base = dataset.cards_by_id[base_id]
    awakened_id = dataset.awakened_ids_by_base_id[base_id]
    return base, dataset.cards_by_id[awakened_id]


def _format_autocard_entry(
    dataset: _AutocardDataset,
    kind: str,
    item: dict[str, Any],
) -> str:
    if kind == "role":
        return _format_role(dataset, item)
    if kind == "card_group":
        base, awakened = _card_pair(dataset, item)
        if awakened is not None:
            return _format_card_group(dataset, base, awakened)
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
                label=(
                    f"{_entry_display_name(dataset, kind, item)}"
                    f"（{_prompt_desc(dataset, kind, item)}）"
                )
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


def _load_role_rows(session: Session) -> tuple[dict[str, Any], ...]:
    try:
        rows = session.execute(_AUTOCARD_ROLE_QUERY).all()
    except SQLAlchemyError:
        return _load_legacy_role_rows(session)

    result: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        values = (
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
        item = json.loads(str(values["raw_json"]))
        if not isinstance(item, dict):
            continue
        item.update(
            {
                "id": int(values["id"]),
                "name": str(values["name"]),
                "desc": str(values["description"]),
                "health": int(values["health"]),
                "skillTxt": str(values["skill_desc"]),
                "nature": int(values["element_type_id"]),
                "picID": int(values["pic_id"]),
                "skillID": int(values["skill_id"]),
                "skillName": str(values["skill_name"]),
                "skillUpgrade": str(values["skill_upgrade"]),
            }
        )
        result.append(item)
    return tuple(result)


def _load_legacy_role_rows(session: Session) -> tuple[dict[str, Any], ...]:
    rows = session.execute(_LEGACY_AUTOCARD_ROLE_QUERY).all()
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


def _entry_display_name(
    dataset: _AutocardDataset,
    kind: str,
    item: dict[str, Any],
) -> str:
    base_name = _entry_name(item)
    if kind != "card_group":
        return base_name
    _base, awakened = _card_pair(dataset, item)
    if awakened is None or _entry_name(awakened) == base_name:
        return base_name
    return f"{base_name} / {_entry_name(awakened)}"


def _card_variant(item: dict[str, Any]) -> str:
    return "金色" if _int_field(item, "compose") else "普通"


def _autocard_image_name(kind: str, item: dict[str, Any]) -> str:
    if kind == "role":
        pic_id = _int_field(item, "picID", "pic_id")
        return f"role_{pic_id}" if pic_id > 0 else ""

    item_id = _int_field(item, "id")
    pic_id = _int_field(item, "picID", "pic_id")
    image_id = (
        pic_id if item_id < _AUTOCARD_NON_PET_CARD_ID_START and pic_id > 0 else item_id
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


def _format_card_group(
    dataset: _AutocardDataset,
    base: dict[str, Any],
    awakened: dict[str, Any],
) -> str:
    type_id = _int_field(base, "type")
    base_name = _entry_name(base)
    awakened_name = _entry_name(awakened)
    identity = (
        f"{base_name}（普通ID：{_int_field(base, 'id')}｜"
        f"觉醒ID：{_int_field(awakened, 'id')}）"
        if base_name == awakened_name
        else (
            f"普通：{base_name}（ID：{_int_field(base, 'id')}）｜"
            f"觉醒：{awakened_name}（ID：{_int_field(awakened, 'id')}）"
        )
    )
    lines = [
        "🃏【群星牌】",
        identity,
        (
            f"类型：{_CARD_TYPE_NAMES.get(type_id, f'类型{type_id}')}"
            f"｜属性：{_nature_name(dataset, _int_field(base, 'nature'))}"
            f"｜等级：{_int_field(base, 'level')}"
            f"｜费用：{_int_field(base, 'cost')}"
        ),
    ]
    _append_variant_field(
        lines,
        label="身材",
        base_value=_card_body(base),
        awakened_value=_card_body(awakened),
    )
    _append_variant_field(
        lines,
        label="效果",
        base_value=_clean_text(_field(base, "cardTxt", "card_txt", default="")),
        awakened_value=_clean_text(
            _field(awakened, "cardTxt", "card_txt", default="")
        ),
    )
    _append_variant_field(
        lines,
        label="描述",
        base_value=_clean_text(_field(base, "des", default="")),
        awakened_value=_clean_text(_field(awakened, "des", default="")),
    )
    return "\n".join(lines)


def _card_body(item: dict[str, Any]) -> str:
    attack = _int_field(item, "attack")
    health = _int_field(item, "health")
    return f"{attack}/{health}" if attack or health else ""


def _append_variant_field(
    lines: list[str],
    *,
    label: str,
    base_value: str,
    awakened_value: str,
) -> None:
    if base_value == awakened_value:
        if base_value:
            lines.append(f"{label}：{base_value}")
        return
    lines.append(f"普通{label}：{base_value or '暂无'}")
    lines.append(f"觉醒{label}：{awakened_value or '暂无'}")


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

    if kind == "card_group":
        base, awakened = _card_pair(dataset, item)
        if awakened is not None:
            nature = _nature_name(dataset, _int_field(base, "nature"))
            type_name = _CARD_TYPE_NAMES.get(_int_field(base, "type"), "卡牌")
            return (
                f"{type_name} 普通{_int_field(base, 'id')}/"
                f"觉醒{_int_field(awakened, 'id')} "
                f"Lv{_int_field(base, 'level')} {nature}"
            )

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
    is_role = kind == "role"
    base, awakened = (
        _card_pair(dataset, item) if kind == "card_group" else (item, None)
    )
    primary_image_url = _autocard_image_url("card", base) if awakened else ""
    awakened_image_url = (
        _autocard_image_url("card", awakened) if awakened is not None else ""
    )
    return AutocardEntry(
        kind="card" if kind == "card_group" else kind,
        item_id=_int_field(base, "id"),
        name=_entry_name(base),
        text=_format_autocard_entry(dataset, kind, item),
        image_url=primary_image_url or _autocard_image_url(kind, item),
        description=_clean_text(_field(item, "desc" if is_role else "des", default="")),
        skill_name=(
            _clean_text(_field(item, "skillName", "skill_name", default=""))
            if is_role
            else ""
        ),
        skill_text=_clean_text(
            _field(
                item,
                "skillTxt" if is_role else "cardTxt",
                "skill_txt" if is_role else "card_txt",
                default="",
            )
        ),
        skill_upgrade=(
            _clean_text(_field(item, "skillUpgrade", "skill_upgrade", default=""))
            if is_role
            else ""
        ),
        additional_image_urls=(awakened_image_url,) if awakened_image_url else (),
    )
