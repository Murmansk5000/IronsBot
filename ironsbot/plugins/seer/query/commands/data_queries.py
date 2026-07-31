# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.prompts import PROMPT_STATE_KEY, Prompt, PromptItem, enter_prompt
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.autocard import AutocardPromptValue
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    NEW_ACHIEVEMENTS_COMMANDS,
    NEW_AUTOCARD_CARDS_COMMANDS,
    NEW_AUTOCARD_ROLES_COMMANDS,
    NEW_CONTENT_COMMANDS,
    NEW_EQUIPS_COMMANDS,
    NEW_MINTMARKS_COMMANDS,
    NEW_MOUNTS_COMMANDS,
    NEW_PETS_COMMANDS,
    NEW_SKINS_COMMANDS,
    NEW_SUITS_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.new_content import (
    CATEGORY_NAMES,
    NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentSnapshot,
    new_content_unavailable_message,
)
from ironsbot.services.seer.pet_query import PetImageSelection

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import build_reply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters import Event
    from nonebot.typing import T_State

    from ironsbot.services.seer.data_queries import (
        DataQueryReply,
        SeerDataQueryService,
    )


NEW_CONTENT_SNAPSHOT_KEY = "new_content_snapshot"
NEW_CONTENT_SERVICES_KEY = "new_content_services"


@dataclass(frozen=True, slots=True)
class _NewContentAction:
    kind: str
    category: NewContentCategory | None = None
    item: NewContentItem | None = None


_NEW_CONTENT_INPUT_PATTERN = re.compile(r"(?:[a-i](?:[1-9]\d*)?|0)", re.IGNORECASE)


async def _finish_query(
    operation: Callable[[], Awaitable[DataQueryReply]],
    *,
    matcher: Matcher,
) -> None:
    try:
        reply: DataQueryReply = await operation()
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if isinstance(reply, bytes):
        await MessageFactory(Image(reply)).finish()
        return
    await matcher.finish(reply)


def install(group: SeerMatcherGroup) -> None:
    service: SeerDataQueryService = group.resources.data_queries
    commands = (
        (WEEKLY_PREVIEW_COMMANDS, "seer_data_preview", service.weekly_preview),
        (DATA_VERSION_COMMANDS, "seer_data_version", service.data_version),
        (
            SEASON_COUNTDOWN_COMMANDS,
            "seer_season_countdown",
            service.season_countdown,
        ),
    )
    rule = seer_feature_rule(group.features, "seer_data") & no_reply()
    for messages, command_id, operation in commands:
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(
                command_id,
                help_ids=("seer.data.query",),
            ),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(bind_async(_finish_query, operation))

    _install_new_content_commands(group, service)


def _install_new_content_commands(
    group: SeerMatcherGroup,
    service: SeerDataQueryService,
) -> None:
    root_rule = seer_feature_rule(group.features, "seer_data") & no_reply()
    root = group.on_fullmatch(
        NEW_CONTENT_COMMANDS,
        policy=CommandPolicy.command(
            "seer.data.new_content",
            help_ids=("seer.data.new_content",),
        ),
        rule=root_rule,
        priority=group.matcher_priority("seer_data"),
    )
    root.append_handler(bind_async(_start_new_content, service, None, group))

    commands: tuple[
        tuple[NewContentCategory, tuple[str, ...], str, str | None], ...
    ] = (
        ("achievement", NEW_ACHIEVEMENTS_COMMANDS, "seer.data.new_achievement", None),
        ("pet", NEW_PETS_COMMANDS, "seer.data.new_pet", "seer_pet"),
        ("pet_skin", NEW_SKINS_COMMANDS, "seer.data.new_skin", "seer_pet"),
        ("mintmark", NEW_MINTMARKS_COMMANDS, "seer.data.new_mintmark", "seer_mintmark"),
        ("suit", NEW_SUITS_COMMANDS, "seer.data.new_suit", "seer_equipment"),
        ("equip", NEW_EQUIPS_COMMANDS, "seer.data.new_equip", "seer_equipment"),
        ("mount", NEW_MOUNTS_COMMANDS, "seer.data.new_mount", "seer_equipment"),
        (
            "autocard_card",
            NEW_AUTOCARD_CARDS_COMMANDS,
            "seer.data.new_autocard_card",
            "seer_autocard",
        ),
        (
            "autocard_role",
            NEW_AUTOCARD_ROLES_COMMANDS,
            "seer.data.new_autocard_role",
            "seer_autocard",
        ),
    )
    for category, messages, command_id, feature in commands:
        rule = root_rule
        if feature is not None:
            rule = rule & seer_feature_rule(group.features, feature)
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(command_id, help_ids=(command_id,)),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(bind_async(_start_new_content, service, category, group))


async def _start_new_content(  # noqa: PLR0913
    service: SeerDataQueryService,
    category: NewContentCategory | None,
    group: SeerMatcherGroup,
    matcher: Matcher,
    state: T_State,
    event: Event,
) -> None:
    try:
        snapshot = service.new_content_snapshot()
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    except NewContentIndexUnavailableError:
        await matcher.finish(new_content_unavailable_message())
        return
    if not snapshot.baseline_established:
        await matcher.finish(new_content_unavailable_message(snapshot))
        return

    available = _available_categories(group, event)
    if category is not None and category not in available:
        await matcher.finish("当前群未开放此新增内容分类。")
        return
    if category is not None and not snapshot.items_for(category):
        await matcher.finish(f"本周暂无{CATEGORY_NAMES[category]}。")
        return
    visible_categories = tuple(
        item for item in available if snapshot.items_for(item)
    )
    if not visible_categories:
        await matcher.finish("本周暂未检测到新增或修改内容。")
        return
    prompt = (
        _content_prompt(snapshot, visible_categories)
        if category is None
        else _content_prompt(snapshot, (category,))
    )
    state[NEW_CONTENT_SNAPSHOT_KEY] = snapshot
    state[NEW_CONTENT_SERVICES_KEY] = _NewContentServices(
        pet=group.resources.pet_query,
        mintmark=group.resources.mintmark,
        equipment=group.resources.equipment,
        autocard=group.resources.autocard,
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_new_content_selection,
        _is_new_content_input,
    )


def _available_categories(
    group: SeerMatcherGroup,
    event: Event,
) -> tuple[NewContentCategory, ...]:
    from ironsbot.runtime.feature_policy import event_is_feature_allowed

    required_features: dict[NewContentCategory, str | None] = {
        "pet": "seer_pet",
        "pet_skin": "seer_pet",
        "mintmark": "seer_mintmark",
        "suit": "seer_equipment",
        "equip": "seer_equipment",
        "mount": "seer_equipment",
        "achievement": None,
        "autocard_card": "seer_autocard",
        "autocard_role": "seer_autocard",
    }
    return tuple(
        category
        for category in NEW_CONTENT_CATEGORIES
        if required_features[category] is None
        or event_is_feature_allowed(group.features, event, required_features[category])
    )


def _is_new_content_input(event: Event) -> bool:
    return bool(_NEW_CONTENT_INPUT_PATTERN.fullmatch(event.get_plaintext().strip()))


def _content_prompt(
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
) -> Prompt[_NewContentAction]:
    choices: list[PromptItem[_NewContentAction]] = []
    for position, category in enumerate(categories):
        code = chr(ord("a") + position)
        items = snapshot.items_for(category)
        choices.append(
            PromptItem(
                CATEGORY_NAMES[category],
                f"{len(items)} 项",
                _NewContentAction("category", category),
                key=code,
            )
        )
        choices.extend(
            PromptItem(
                item.name,
                _item_description(item),
                _NewContentAction("item", category, item),
                is_sub_prompt=True,
                key=f"{code}{index}",
            )
            for index, item in enumerate(items, start=1)
        )
    return Prompt(
        title="🆕【新增内容】输入编号查看详情：",
        items=choices,
    )


def _item_description(item: NewContentItem) -> str:
    change = "修改" if item.change_kind == "modified" else "新增"
    if item.category == "achievement":
        point = int(item.payload.get("point", 0))
        titles = item.payload.get("titles", [])
        title_text = f"｜称号：{titles[0].get('name', '')}" if titles else ""
        return f"{change}｜{item.entity_id}｜{point} 点{title_text}"
    if item.category == "pet_skin":
        pet_name = str(item.payload.get("pet_name", ""))
        return f"{change}｜{item.entity_id}｜{pet_name or '未关联精灵'}"
    if item.category in {"autocard_card", "autocard_role"}:
        kind = "角色" if item.category == "autocard_role" else "卡牌"
        return f"{change}｜{item.entity_id}｜{kind}"
    return f"{change}｜{item.entity_id}"


async def _resolve_new_content_selection(
    selection: PromptItem[_NewContentAction],
    matcher: Matcher,
    event: Event,
) -> None:
    action = selection.value
    snapshot = matcher.state.get(NEW_CONTENT_SNAPSHOT_KEY)
    if not isinstance(snapshot, NewContentSnapshot):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    if action.kind == "category" and action.category is not None:
        await _replace_prompt(
            matcher,
            event,
            _content_prompt(snapshot, (action.category,)),
        )
        return
    if action.item is not None:
        await _send_item_detail(action.item, matcher)


async def _replace_prompt(
    matcher: Matcher,
    event: Event,
    prompt: Prompt[_NewContentAction],
) -> None:
    matcher.state[PROMPT_STATE_KEY] = prompt
    await MessageFactory(prompt.build_event_message(event)).send()


async def _send_item_detail(item: NewContentItem, matcher: Matcher) -> None:
    services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
    if not isinstance(services, _NewContentServices):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    if item.category == "achievement":
        await MessageFactory(_achievement_detail(item)).send()
        return
    try:
        if item.category in {"autocard_card", "autocard_role"}:
            await _send_autocard_detail(item, services.autocard)
            return
        result = await _select_standard_item(item, services)
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if result.message:
        await MessageFactory(result.message).send()
    elif result.reply is not None:
        await build_reply(result.reply).send()


async def _select_standard_item(
    item: NewContentItem,
    services: _NewContentServices,
) -> Any:
    if item.category == "pet":
        return await services.pet.select_info(item.entity_id)
    if item.category == "pet_skin":
        return await services.pet.select_image(
            PetImageSelection(
                resource_id=int(item.payload.get("resource_id", item.entity_id)),
                name=item.name,
                skin_id=item.entity_id,
            )
        )
    if item.category == "mintmark":
        return await services.mintmark.select_mintmark(item.entity_id)
    if item.category == "suit":
        return await services.equipment.select("suit", item.entity_id)
    return await services.equipment.select("equip", item.entity_id)


async def _send_autocard_detail(item: NewContentItem, service: Any) -> None:
    entry = service.select(
        AutocardPromptValue(
            kind="role" if item.category == "autocard_role" else "card",
            item_id=item.entity_id,
        )
    )
    if entry is None:
        return
    message = MessageFactory(entry.text)
    if entry.image_url:
        message = MessageFactory(Image(entry.image_url)) + message
    await message.send()


def _achievement_detail(item: NewContentItem) -> str:
    lines = [
        f"🏆【{item.name}】",
        f"🆔：{item.entity_id}",
        f"成就点数：{int(item.payload.get('point', 0))}点",
    ]
    description = str(item.payload.get("description", "")).strip()
    if description:
        lines.append(f"说明：{description}")
    titles = item.payload.get("titles", [])
    if isinstance(titles, list) and titles:
        names = "、".join(str(title.get("name", "")) for title in titles)
        lines.append(f"关联称号：{names}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _NewContentServices:
    pet: Any
    mintmark: Any
    equipment: Any
    autocard: Any
