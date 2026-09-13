# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.selection import (
    SelectionMenuItem,
    format_selection_menu,
)
from ironsbot.integrations.seer_data.autocard_repository import (
    AutocardDataset,
    load_autocard_dataset,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataReader

AUTOCARD_PROMPT_MAX_ITEMS = 30
AUTOCARD_QUERY_PREFIXES = ("群星牌", "卡牌", "查询群星牌")
AUTOCARD_QUERY_SUFFIXES = ("群星牌",)

_AUTOCARD_NAME_STRIP_PATTERN = re.compile(r"[\s.·・•‧∙⋅。\-_/]+")
_CARD_TYPE_NAMES = {
    1: "精灵牌",
    2: "法术牌",
    3: "衍生精灵牌",
    4: "特殊牌",
}
_AUTOCARD_NON_PET_CARD_ID_START = 20000
logger = logging.getLogger(__name__)


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
    image_key: str
    description: str = ""
    skill_name: str = ""
    skill_text: str = ""
    skill_upgrade: str = ""
    additional_image_keys: tuple[str, ...] = ()

    @property
    def image_keys(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                key for key in (self.image_key, *self.additional_image_keys) if key
            )
        )

    def to_outbound(
        self,
        *,
        image_contents: tuple[bytes, ...] = (),
    ) -> OutboundMessage:
        parts: list[BinaryImagePart | TextPart] = [
            BinaryImagePart(content, "image/png") for content in image_contents
        ]
        parts.append(TextPart(self.text))
        return OutboundMessage(tuple(parts))


@dataclass(slots=True, frozen=True)
class AutocardSearchResult:
    entry: AutocardEntry | None = None
    prompt_values: tuple[AutocardPromptValue, ...] = ()
    prompt_text: str = ""
    message: str = ""


@dataclass(slots=True, frozen=True)
class _AutocardIndex:
    dataset: AutocardDataset
    cards_by_id: dict[int, dict[str, Any]]
    base_id_by_card_id: dict[int, int]
    awakened_id_by_base_id: dict[int, int]


class AutocardService:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def search(self, arg: str) -> AutocardSearchResult:
        with self._data.query(load_autocard_dataset) as dataset:
            index = _build_autocard_index(dataset)
            matches = _search_autocard_items(
                index,
                _extract_autocard_query_arg(arg),
            )
        if not matches:
            return AutocardSearchResult()
        if len(matches) == 1:
            kind, item = matches[0]
            return AutocardSearchResult(entry=_build_entry(index, kind, item))
        if len(matches) > AUTOCARD_PROMPT_MAX_ITEMS:
            return AutocardSearchResult(
                message=(
                    f"❌ 群星牌匹配超过 {AUTOCARD_PROMPT_MAX_ITEMS} 个，"
                    "请换更精确的关键词。"
                )
            )
        return AutocardSearchResult(
            prompt_values=_build_autocard_prompt_values(matches),
            prompt_text=_build_autocard_prompt_text(index, matches),
        )

    def select(self, value: AutocardPromptValue) -> AutocardEntry | None:
        with self._data.query(load_autocard_dataset) as dataset:
            index = _build_autocard_index(dataset)
            item = (
                _find_autocard_role_by_id(dataset, value.item_id)
                if value.kind == "role"
                else _find_autocard_card_by_id(index, value.item_id)
            )
        return None if item is None else _build_entry(index, value.kind, item)


def _build_autocard_index(dataset: AutocardDataset) -> _AutocardIndex:
    cards_by_id = {_int_field(card, "id"): card for card in dataset.cards}
    base_id_by_card_id: dict[int, int] = {}
    awakened_id_by_base_id: dict[int, int] = {}
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
        if target_id in base_id_by_card_id:
            logger.warning(
                "duplicate autocard compose target: target_id=%s base_ids=%s,%s",
                target_id,
                base_id_by_card_id[target_id],
                base_id,
            )
            continue
        base_id_by_card_id[base_id] = base_id
        base_id_by_card_id[target_id] = base_id
        awakened_id_by_base_id[base_id] = target_id
    return _AutocardIndex(
        dataset=dataset,
        cards_by_id=cards_by_id,
        base_id_by_card_id=base_id_by_card_id,
        awakened_id_by_base_id=awakened_id_by_base_id,
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


def _find_autocard_card_by_id(
    index: _AutocardIndex,
    item_id: int,
) -> dict[str, Any] | None:
    return index.cards_by_id.get(item_id)


def _find_autocard_role_by_id(
    dataset: AutocardDataset,
    item_id: int,
) -> dict[str, Any] | None:
    for item in dataset.roles:
        if _int_field(item, "id") == item_id:
            return item
    return None


def _search_autocard_items(
    index: _AutocardIndex,
    query: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = query.strip()
    if not query or query.isdigit():
        return []
    if query.startswith("卡") and query[1:].isdigit():
        card = _find_autocard_card_by_id(index, int(query[1:]))
        if card is None:
            return []
        base, awakened = _card_pair(index, card)
        return [("card_group" if awakened is not None else "card", base)]

    normalized_query = _normalize_name(query)
    entries = _grouped_card_search_entries(index) + [
        ("role", role) for role in index.dataset.roles
    ]
    exact = [
        (kind, item)
        for kind, item in entries
        if normalized_query in _entry_search_names(index, kind, item)
    ]
    if exact:
        return exact

    return [
        (kind, item)
        for kind, item in entries
        if any(
            normalized_query in name for name in _entry_search_names(index, kind, item)
        )
    ]


def _grouped_card_search_entries(
    index: _AutocardIndex,
) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    consumed_ids: set[int] = set()
    for card in index.dataset.cards:
        item_id = _int_field(card, "id")
        if item_id in consumed_ids:
            continue
        base, awakened = _card_pair(index, card)
        consumed_ids.add(_int_field(base, "id"))
        if awakened is not None:
            consumed_ids.add(_int_field(awakened, "id"))
        entries.append(("card_group" if awakened is not None else "card", base))
    return entries


def _entry_search_names(
    index: _AutocardIndex,
    kind: str,
    item: dict[str, Any],
) -> tuple[str, ...]:
    names = [_normalize_name(_entry_name(item))]
    if kind == "card_group":
        _base, awakened = _card_pair(index, item)
        if awakened is not None:
            names.append(_normalize_name(_entry_name(awakened)))
    return tuple(dict.fromkeys(names))


def _card_pair(
    index: _AutocardIndex,
    item: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    item_id = _int_field(item, "id")
    base_id = index.base_id_by_card_id.get(item_id)
    if base_id is None:
        return item, None
    base = index.cards_by_id[base_id]
    awakened_id = index.awakened_id_by_base_id[base_id]
    return base, index.cards_by_id[awakened_id]


def _format_autocard_entry(
    index: _AutocardIndex,
    kind: str,
    item: dict[str, Any],
) -> str:
    if kind == "role":
        return _format_role(index.dataset, item)
    if kind == "card_group":
        base, awakened = _card_pair(index, item)
        if awakened is not None:
            return _format_card_group(index.dataset, base, awakened)
    return _format_card(index.dataset, item)


def _build_autocard_prompt_values(
    matches: list[tuple[str, dict[str, Any]]],
) -> tuple[AutocardPromptValue, ...]:
    return tuple(
        AutocardPromptValue(kind=kind, item_id=_int_field(item, "id"))
        for kind, item in matches
    )


def _build_autocard_prompt_text(
    index: _AutocardIndex,
    matches: list[tuple[str, dict[str, Any]]],
) -> str:
    return format_selection_menu(
        title="请问你想查询的群星牌资料是……",
        items=tuple(
            SelectionMenuItem(
                label=(
                    f"{_entry_display_name(index, kind, item)}"
                    f"（{_prompt_desc(index, kind, item)}）"
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


def _entry_name(item: dict[str, Any]) -> str:
    return str(_field(item, "name", default=""))


def _entry_display_name(
    index: _AutocardIndex,
    kind: str,
    item: dict[str, Any],
) -> str:
    base_name = _entry_name(item)
    if kind != "card_group":
        return base_name
    _base, awakened = _card_pair(index, item)
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


def _nature_name(dataset: AutocardDataset, nature_id: int) -> str:
    if nature_id <= 0:
        return "无"
    return dataset.natures.get(nature_id, f"属性{nature_id}")


def _format_card(dataset: AutocardDataset, item: dict[str, Any]) -> str:
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
    dataset: AutocardDataset,
    base: dict[str, Any],
    awakened: dict[str, Any],
) -> str:
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
            f"类型：{_CARD_TYPE_NAMES.get(_int_field(base, 'type'), '卡牌')}"
            f" | 属性：{_nature_name(dataset, _int_field(base, 'nature'))}"
            f" | 等级：{_int_field(base, 'level')}"
            f" | 费用：{_int_field(base, 'cost')}"
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
        awakened_value=_clean_text(_field(awakened, "cardTxt", "card_txt", default="")),
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


def _format_role(dataset: AutocardDataset, item: dict[str, Any]) -> str:
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


def _prompt_desc(index: _AutocardIndex, kind: str, item: dict[str, Any]) -> str:
    item_id = _int_field(item, "id")
    if kind == "role":
        nature = _nature_name(index.dataset, _int_field(item, "nature"))
        return f"角色 {item_id} {nature}"

    if kind == "card_group":
        base, awakened = _card_pair(index, item)
        if awakened is not None:
            nature = _nature_name(index.dataset, _int_field(base, "nature"))
            type_name = _CARD_TYPE_NAMES.get(_int_field(base, "type"), "卡牌")
            return (
                f"{type_name} 普通{_int_field(base, 'id')}/"
                f"觉醒{_int_field(awakened, 'id')} "
                f"Lv{_int_field(base, 'level')} {nature}"
            )

    nature = _nature_name(index.dataset, _int_field(item, "nature"))
    type_name = _CARD_TYPE_NAMES.get(_int_field(item, "type"), "卡牌")
    return (
        f"{type_name} {item_id} {_card_variant(item)} "
        f"Lv{_int_field(item, 'level')} {nature}"
    )


def _build_entry(
    index: _AutocardIndex,
    kind: str,
    item: dict[str, Any],
) -> AutocardEntry:
    is_role = kind == "role"
    base, awakened = _card_pair(index, item) if kind == "card_group" else (item, None)
    awakened_image_key = (
        _autocard_image_name("card", awakened) if awakened is not None else ""
    )
    return AutocardEntry(
        kind="card" if kind == "card_group" else kind,
        item_id=_int_field(base, "id"),
        name=_entry_name(base),
        text=_format_autocard_entry(index, kind, item),
        image_key=_autocard_image_name("card", base)
        if awakened
        else _autocard_image_name(kind, item),
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
        additional_image_keys=(awakened_image_key,) if awakened_image_key else (),
    )
