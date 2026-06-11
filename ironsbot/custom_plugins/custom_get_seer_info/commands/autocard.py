# SPDX-License-Identifier: GPL-3.0-or-later
import json
import re
from dataclasses import dataclass
from typing import Any

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.custom_plugins.message_actions import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.plugins.seer_data.db import SeerAPISession
from ironsbot.shared.messaging.conversations import event_conversation_session_id
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.matcher import prompt_session_manager
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group

AUTOCARD_PROMPT_MAX_ITEMS = 30
AUTOCARD_PROMPT_NAMESPACE = "autocard"
AUTOCARD_PROMPT_STATE_KEY = "_autocard_prompt_values"
AUTOCARD_QUERY_PREFIXES = ("群星牌", "卡牌", "查询群星牌")
AUTOCARD_QUERY_SUFFIXES = ("群星牌",)
AUTOCARD_HELP_ARGS = {"", "帮助", "查询", "资料", "说明"}
AUTOCARD_NAME_STRIP_PATTERN = re.compile(r"[\s.·・•‧∙⋅。\-_/]+")
AUTOCARD_MISSING_TABLE_MESSAGE = "数据库缺少群星牌表，请先更新 IronsBot 数据库。"
AUTOCARD_EMPTY_DATA_MESSAGE = "数据库没有群星牌数据，请先更新 IronsBot 数据库。"
AUTOCARD_PLUGIN_NAME = "seer_autocard"

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


@dataclass(slots=True, frozen=True)
class AutocardPromptValue:
    kind: str
    item_id: int


autocard_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=AUTOCARD_QUERY_PREFIXES,
        suffixes=AUTOCARD_QUERY_SUFFIXES,
    )
    & no_reply()
)


def _normalize_name(value: object) -> str:
    return AUTOCARD_NAME_STRIP_PATTERN.sub("", str(value)).casefold()


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


def _load_autocard_dataset(session: SeerAPISession) -> AutocardDataset:
    try:
        cards = _load_json_rows(session, "autocard_card")
        roles = _load_json_rows(session, "autocard_role")
        nature_rows = _load_json_rows(session, "autocard_nature")
    except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(AUTOCARD_MISSING_TABLE_MESSAGE) from e

    if not cards and not roles:
        raise RuntimeError(AUTOCARD_EMPTY_DATA_MESSAGE)

    natures = {
        _int_field(row, "id"): str(_field(row, "name"))
        for row in nature_rows
    }
    return AutocardDataset(
        cards=cards,
        roles=roles,
        natures=natures,
    )


def _load_json_rows(
    session: SeerAPISession,
    table_name: str,
) -> tuple[dict[str, Any], ...]:
    rows = session.exec(
        text(f"SELECT raw_json FROM {table_name} ORDER BY id")
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        raw_json = mapping["raw_json"] if mapping is not None else row[0]
        item = json.loads(str(raw_json))
        if isinstance(item, dict):
            result.append(item)
    return tuple(result)


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


def _is_autocard_prompt_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


def _invalidate_autocard_prompt(event: MessageEvent) -> None:
    prompt_session_manager.invalidate(
        event_conversation_session_id(AUTOCARD_PROMPT_NAMESPACE, event)
    )


def _prompt_values(
    matches: list[tuple[str, dict[str, Any]]],
) -> tuple[AutocardPromptValue, ...]:
    return tuple(
        AutocardPromptValue(kind=kind, item_id=_int_field(item, "id"))
        for kind, item in matches
    )


def _build_prompt_text(
    dataset: AutocardDataset,
    matches: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = ["请问你想查询的群星牌资料是……"]
    for index, (kind, item) in enumerate(matches, start=1):
        desc = _prompt_desc(dataset, kind, item)
        lines.append(f"{index}. {_entry_name(item)}（{desc}）")
    lines.append("")
    lines.append("💬 输入序号选择 · 输入 0 退出")
    return "\n".join(lines)


async def _enter_autocard_prompt(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    values: tuple[AutocardPromptValue, ...],
    prompt: str | None,
) -> None:
    state[AUTOCARD_PROMPT_STATE_KEY] = values
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=AUTOCARD_PROMPT_NAMESPACE,
        handlers=[_handle_autocard_prompt_reply],
        reply_check=_is_autocard_prompt_reply,
        prompt=prompt,
    )


async def _handle_autocard_prompt_reply(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=AUTOCARD_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="prompt_reply",
        session=session,
    )


class AutocardPlugin:
    name = AUTOCARD_PLUGIN_NAME
    feature = "seer"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        session: SeerAPISession = context.data["session"]
        if context.action == "prompt_reply":
            await self._handle_prompt_reply(matcher, event, state, session)
            return
        if context.action == "query":
            arg = str(context.data.get("arg", ""))
            await self._handle_query(matcher, event, state, session, arg)

    async def _handle_prompt_reply(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
        session: SeerAPISession,
    ) -> None:
        key_text = event.get_plaintext().strip()
        if key_text == "0":
            await finish_event_reply(matcher, event, "❌ 已退出群星牌选择")

        values = tuple(state.get(AUTOCARD_PROMPT_STATE_KEY) or ())
        if not values:
            raise FinishedException

        index = int(key_text)
        if index < 1 or index > len(values):
            await finish_event_reply(
                matcher,
                event,
                "⚠️ 序号超出范围，已退出群星牌选择",
            )

        value = values[index - 1]
        dataset = _load_autocard_dataset(session)
        if value.kind == "role":
            data = _find_role_by_id(dataset, value.item_id)
        else:
            data = _find_card_by_id(dataset, value.item_id)

        if data is None:
            await finish_event_reply(
                matcher,
                event,
                "❌ 未找到该群星牌资料，这可能是数据库数据已更新或缺失。",
            )

        await send_event_reply(matcher, event, _format_entry(dataset, value.kind, data))
        await _enter_autocard_prompt(matcher, event, state, values, prompt=None)

    async def _handle_query(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
        session: SeerAPISession,
        arg: str,
    ) -> None:
        _invalidate_autocard_prompt(event)

        query = _extract_query_arg(arg)
        if query in AUTOCARD_HELP_ARGS:
            await finish_event_reply(matcher, event, format_autocard_public_info())

        try:
            dataset = _load_autocard_dataset(session)
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
            await finish_event_reply(
                matcher,
                event,
                _format_entry(dataset, kind, item),
            )

        if len(matches) > AUTOCARD_PROMPT_MAX_ITEMS:
            message = (
                f"❌ 群星牌匹配超过 {AUTOCARD_PROMPT_MAX_ITEMS} 个，"
                "请换更精确的关键词。"
            )
            await finish_event_reply(
                matcher,
                event,
                message,
            )

        await _enter_autocard_prompt(
            matcher,
            event,
            state,
            _prompt_values(matches),
            prompt=_build_prompt_text(dataset, matches),
        )


register_plugin(AutocardPlugin())


@autocard_matcher.handle()
async def handle_autocard_query(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
) -> None:
    await dispatch_plugin(
        plugin_name=AUTOCARD_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="query",
        session=session,
        arg=arg,
    )
