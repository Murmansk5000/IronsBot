# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.prompt import Prompt, PromptItem, enter_prompt
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group

AUTOCARD_CONFIG_BASE_URLS = (
    "https://raw.githubusercontent.com/WhY15w/seer-unity-config-parser/main/json",
    "https://cdn.jsdelivr.net/gh/WhY15w/seer-unity-config-parser@main/json",
)
AUTOCARD_CONTENT_FILE = "autocardContent.json"
AUTOCARD_NATURE_FILE = "autocardNature.json"
AUTOCARD_ROLE_FILE = "autocardRole.json"
AUTOCARD_CACHE_TTL = timedelta(hours=12)
AUTOCARD_PROMPT_MAX_ITEMS = 30
AUTOCARD_QUERY_PREFIXES = ("群星牌", "卡牌", "查询群星牌")
AUTOCARD_QUERY_SUFFIXES = ("群星牌",)
AUTOCARD_HELP_ARGS = {"", "帮助", "查询", "资料", "说明"}
AUTOCARD_NAME_STRIP_PATTERN = re.compile(r"[\s.·・•‧∙⋅。\-_/]+")

CARD_TYPE_NAMES = {
    1: "精灵牌",
    2: "法术牌",
    3: "衍生精灵牌",
    4: "特殊牌",
}


@dataclass(slots=True, frozen=True)
class AutocardDataset:
    cards: tuple[dict[str, Any], ...]
    roles: tuple[dict[str, Any], ...]
    natures: dict[int, str]
    fetched_at: datetime


@dataclass(slots=True, frozen=True)
class AutocardPromptValue:
    kind: str
    item_id: int


_autocard_cache: AutocardDataset | None = None
_autocard_cache_lock = asyncio.Lock()


autocard_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=AUTOCARD_QUERY_PREFIXES,
        suffixes=AUTOCARD_QUERY_SUFFIXES,
    )
    & no_reply()
)


def _normalize_name(value: object) -> str:
    return AUTOCARD_NAME_STRIP_PATTERN.sub("", str(value)).casefold()


def _null_prompt_session() -> None:
    return None


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


def _extract_query_arg(arg: str) -> str:
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


async def _fetch_json_file(filename: str) -> dict[str, Any]:
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for base_url in AUTOCARD_CONFIG_BASE_URLS:
            try:
                response = await client.get(f"{base_url}/{filename}")
                response.raise_for_status()
                return response.json()
            except Exception as e:  # noqa: BLE001, PERF203
                last_error = e

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"无法获取群星牌配置：{filename}")


async def _load_autocard_dataset() -> AutocardDataset:
    global _autocard_cache  # noqa: PLW0603
    now = datetime.now(tz=timezone.utc)
    if (
        _autocard_cache is not None
        and now - _autocard_cache.fetched_at < AUTOCARD_CACHE_TTL
    ):
        return _autocard_cache

    async with _autocard_cache_lock:
        if (
            _autocard_cache is not None
            and now - _autocard_cache.fetched_at < AUTOCARD_CACHE_TTL
        ):
            return _autocard_cache

        content_json, nature_json, role_json = await asyncio.gather(
            _fetch_json_file(AUTOCARD_CONTENT_FILE),
            _fetch_json_file(AUTOCARD_NATURE_FILE),
            _fetch_json_file(AUTOCARD_ROLE_FILE),
        )
        natures = {
            _int_field(row, "id"): str(_field(row, "name"))
            for row in nature_json.get("data", [])
        }
        _autocard_cache = AutocardDataset(
            cards=tuple(content_json.get("data", [])),
            roles=tuple(role_json.get("data", [])),
            natures=natures,
            fetched_at=now,
        )
        return _autocard_cache


def format_autocard_public_info() -> str:
    return "\n".join(
        (
            "🃏【群星牌查询】",
            "发送“群星牌+名字”或“名字+群星牌”查询卡牌/赛尔角色资料。",
            "示例：群星牌布布种子、金币卡群星牌、卡牌金币卡、群星牌破界者",
            "",
            "当前查询公开配置：卡牌、属性、等级、费用、基础攻血、效果文本、赛尔角色技能。",
            "个人积分、常用卡、历史对局暂不支持。",
        )
    )


def _entry_name(item: dict[str, Any]) -> str:
    return str(_field(item, "name", default=""))


def _find_card_by_id(dataset: AutocardDataset, item_id: int) -> dict[str, Any] | None:
    for item in dataset.cards:
        if _int_field(item, "id") == item_id:
            return item
    return None


def _find_role_by_id(dataset: AutocardDataset, item_id: int) -> dict[str, Any] | None:
    for item in dataset.roles:
        if _int_field(item, "id") == item_id:
            return item
    return None


def _search_items(
    dataset: AutocardDataset,
    query: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = query.strip()
    if query.isdigit():
        item_id = int(query)
        matches: list[tuple[str, dict[str, Any]]] = []
        if card := _find_card_by_id(dataset, item_id):
            matches.append(("card", card))
        if role := _find_role_by_id(dataset, item_id):
            matches.append(("role", role))
        return matches

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


def _card_variant(item: dict[str, Any]) -> str:
    return "金色" if _int_field(item, "compose") else "普通"


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
            f"类型：{CARD_TYPE_NAMES.get(type_id, f'类型{type_id}')}"
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


def _format_entry(dataset: AutocardDataset, kind: str, item: dict[str, Any]) -> str:
    if kind == "role":
        return _format_role(dataset, item)
    return _format_card(dataset, item)


def _prompt_desc(dataset: AutocardDataset, kind: str, item: dict[str, Any]) -> str:
    item_id = _int_field(item, "id")
    if kind == "role":
        nature = _nature_name(dataset, _int_field(item, "nature"))
        return f"角色 {item_id} {nature}"

    nature = _nature_name(dataset, _int_field(item, "nature"))
    type_name = CARD_TYPE_NAMES.get(_int_field(item, "type"), "卡牌")
    return (
        f"{type_name} {item_id} {_card_variant(item)} "
        f"Lv{_int_field(item, 'level')} {nature}"
    )


async def _resolve_autocard_prompt(
    item: PromptItem[AutocardPromptValue],
    matcher: Matcher,
    _: Any,
) -> None:
    dataset = await _load_autocard_dataset()
    if item.value.kind == "role":
        data = _find_role_by_id(dataset, item.value.item_id)
    else:
        data = _find_card_by_id(dataset, item.value.item_id)

    if data is None:
        await matcher.finish("❌ 未找到该群星牌资料，这可能是缓存已过期。")

    await matcher.send(_format_entry(dataset, item.value.kind, data))


@autocard_matcher.handle()
async def handle_autocard_query(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    arg: str = Depends(parse_string_arg),
) -> None:
    query = _extract_query_arg(arg)
    if query in AUTOCARD_HELP_ARGS:
        await finish_event_reply(matcher, event, format_autocard_public_info())

    try:
        dataset = await _load_autocard_dataset()
    except Exception as e:  # noqa: BLE001
        await finish_event_reply(
            matcher,
            event,
            f"❌ 群星牌公开配置获取失败：{e}",
        )

    matches = _search_items(dataset, query)
    if not matches:
        raise FinishedException

    if len(matches) == 1:
        kind, item = matches[0]
        await finish_event_reply(matcher, event, _format_entry(dataset, kind, item))

    if len(matches) > AUTOCARD_PROMPT_MAX_ITEMS:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 群星牌匹配超过 {AUTOCARD_PROMPT_MAX_ITEMS} 个，请换更精确的关键词。"
        )

    prompt = Prompt(
        title="请问你想查询的群星牌资料是……",
        items=[
            PromptItem(
                name=_entry_name(item),
                desc=_prompt_desc(dataset, kind, item),
                value=AutocardPromptValue(kind=kind, item_id=_int_field(item, "id")),
            )
            for kind, item in matches
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_autocard_prompt,
        session_dependency=Depends(_null_prompt_session),
    )
