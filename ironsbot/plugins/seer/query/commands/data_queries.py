# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from nonebot.adapters import (
    Event,  # noqa: TC002 - NoneBot resolves callback annotations
)
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import (
    T_State,  # noqa: TC002 - NoneBot resolves callback annotations
)
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import (
    CommandPolicy,
    bind_async,
    update_queued_menu_anchor,
)
from ironsbot.runtime.prompts import PROMPT_STATE_KEY, Prompt, PromptItem, enter_prompt
from ironsbot.runtime.rules import command_input
from ironsbot.services.seer.autocard import AutocardPromptValue
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    NEW_ACHIEVEMENTS_COMMANDS,
    NEW_AUTOCARD_CARDS_COMMANDS,
    NEW_AUTOCARD_ROLES_COMMANDS,
    NEW_AUTOCARD_SANCTUARIES_COMMANDS,
    NEW_CONTENT_COMMANDS,
    NEW_EQUIPS_COMMANDS,
    NEW_MINTMARKS_COMMANDS,
    NEW_MOUNTS_COMMANDS,
    NEW_PETS_COMMANDS,
    NEW_SKILLS_COMMANDS,
    NEW_SKINS_COMMANDS,
    NEW_SUITS_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    CATEGORY_NAMES,
    NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentSnapshot,
    new_content_category_unavailable_message,
    new_content_unavailable_message,
)
from ironsbot.services.seer.pet_query import PetImageSelection

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import build_reply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data_queries import (
        DataQueryReply,
        SeerDataQueryService,
    )


NEW_CONTENT_SNAPSHOT_KEY = "new_content_snapshot"
NEW_CONTENT_SERVICES_KEY = "new_content_services"
NEW_CONTENT_MENU_LAYOUT_KEY = "new_content_menu_layout"


@dataclass(frozen=True, slots=True)
class _NewContentAction:
    kind: str
    category: NewContentCategory | None = None
    item: NewContentItem | None = None


@dataclass(frozen=True, slots=True)
class _NewContentMenuLayout:
    """Keep visible categories and their stable root keys separate."""

    display_categories: tuple[NewContentCategory, ...]
    root_categories: tuple[NewContentCategory, ...]
    expanded_categories: frozenset[NewContentCategory]
    focused_category: NewContentCategory | None = None


_NEW_CONTENT_INPUT_PATTERN = re.compile(r"(?:[a-j](?:[1-9]\d*)?|0)", re.IGNORECASE)


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
    rule = seer_feature_rule(group.features, "seer_data") & command_input()
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
    root_rule = seer_feature_rule(group.features, "seer_data") & command_input()
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
        tuple[tuple[NewContentCategory, ...], tuple[str, ...], str, str | None], ...
    ] = (
        (
            ("achievement",),
            NEW_ACHIEVEMENTS_COMMANDS,
            "seer.data.new_achievement",
            None,
        ),
        (("pet",), NEW_PETS_COMMANDS, "seer.data.new_pet", "seer_pet"),
        (("pet_skin",), NEW_SKINS_COMMANDS, "seer.data.new_skin", "seer_pet"),
        (("skill",), NEW_SKILLS_COMMANDS, "seer.data.new_skill", "seer_pet"),
        (
            ("mintmark",),
            NEW_MINTMARKS_COMMANDS,
            "seer.data.new_mintmark",
            "seer_mintmark",
        ),
        (("suit",), NEW_SUITS_COMMANDS, "seer.data.new_suit", "seer_equipment"),
        (("equip",), NEW_EQUIPS_COMMANDS, "seer.data.new_equip", "seer_equipment"),
        (("mount",), NEW_MOUNTS_COMMANDS, "seer.data.new_mount", "seer_equipment"),
        (
            AUTOCARD_NEW_CONTENT_CATEGORIES,
            NEW_AUTOCARD_CARDS_COMMANDS,
            "seer.data.new_autocard",
            "seer_autocard",
        ),
        (
            ("autocard_role",),
            NEW_AUTOCARD_ROLES_COMMANDS,
            "seer.data.new_autocard_role",
            "seer_autocard",
        ),
        (
            ("autocard_sanctuary_effect",),
            NEW_AUTOCARD_SANCTUARIES_COMMANDS,
            "seer.data.new_autocard_sanctuary_effect",
            "seer_autocard",
        ),
    )
    for categories, messages, command_id, feature in commands:
        rule = root_rule
        if feature is not None:
            rule = rule & seer_feature_rule(group.features, feature)
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(command_id, help_ids=(command_id,)),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(
            bind_async(_start_new_content, service, categories, group)
        )


async def _start_new_content(  # noqa: PLR0913
    service: SeerDataQueryService,
    categories: tuple[NewContentCategory, ...] | None,
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

    available = _available_categories(group, event)
    if categories is not None and not set(categories).issubset(available):
        await matcher.finish("当前群未开放此新增内容分类。")
        return
    root_categories: tuple[NewContentCategory, ...] = tuple(
        category
        for category in available
        if snapshot.is_category_comparable(category) and snapshot.items_for(category)
    )
    requested_categories: tuple[NewContentCategory, ...] = (
        categories if categories is not None else available
    )
    comparable_categories: tuple[NewContentCategory, ...] = tuple(
        category
        for category in requested_categories
        if snapshot.is_category_comparable(category)
    )
    if categories is not None and not comparable_categories:
        await matcher.finish(
            new_content_category_unavailable_message(snapshot, categories)
        )
        return
    visible_categories: tuple[NewContentCategory, ...] = tuple(
        category
        for category in comparable_categories
        if snapshot.items_for(category)
    )
    if categories is not None and not visible_categories:
        await matcher.finish(_empty_new_content_message(snapshot, categories))
        return
    if not visible_categories:
        await matcher.finish("本周暂未检测到可验证的新增或修改内容。")
        return
    expanded_categories: frozenset[NewContentCategory] = (
        frozenset(visible_categories)
        if categories is not None
        else frozenset(
            category
            for category in root_categories
            if category in group.new_content.expanded_categories
        )
    )
    layout = _NewContentMenuLayout(
        display_categories=visible_categories,
        root_categories=root_categories,
        expanded_categories=expanded_categories,
        focused_category=(
            categories[0]
            if categories is not None and len(categories) == 1
            else None
        ),
    )
    prompt = _content_prompt(snapshot, layout)
    state[NEW_CONTENT_SNAPSHOT_KEY] = snapshot
    state[NEW_CONTENT_SERVICES_KEY] = _NewContentServices(
        pet=group.resources.pet_query,
        mintmark=group.resources.mintmark,
        equipment=group.resources.equipment,
        autocard=group.resources.autocard,
    )
    state[NEW_CONTENT_MENU_LAYOUT_KEY] = layout
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_new_content_selection,
        _is_new_content_input,
    )


def _empty_new_content_message(
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
) -> str:
    name = (
        "新增群星牌"
        if categories == AUTOCARD_NEW_CONTENT_CATEGORIES
        else CATEGORY_NAMES[categories[0]]
    )
    first_observations: tuple[NewContentCategory, ...] = tuple(
        category
        for category in categories
        if snapshot.category_state(category).reason == "first_observation"
    )
    if first_observations:
        notice = new_content_category_unavailable_message(snapshot, first_observations)
        return f"本周暂无{name}。{notice}"
    return f"本周暂无{name}。"


def _available_categories(
    group: SeerMatcherGroup,
    event: Event,
) -> tuple[NewContentCategory, ...]:
    from ironsbot.runtime.feature_policy import event_is_feature_allowed

    required_features: dict[NewContentCategory, str | None] = {
        "pet": "seer_pet",
        "pet_skin": "seer_pet",
        "skill": "seer_pet",
        "mintmark": "seer_mintmark",
        "suit": "seer_equipment",
        "equip": "seer_equipment",
        "mount": "seer_equipment",
        "achievement": None,
        "autocard_card": "seer_autocard",
        "autocard_role": "seer_autocard",
        "autocard_sanctuary_effect": "seer_autocard",
    }
    available: list[NewContentCategory] = []
    for category in NEW_CONTENT_CATEGORIES:
        required_feature = required_features[category]
        if required_feature is None or event_is_feature_allowed(
            group.features,
            event,
            required_feature,
        ):
            available.append(category)
    return tuple(available)


def _is_new_content_input(event: Event) -> bool:
    return bool(_NEW_CONTENT_INPUT_PATTERN.fullmatch(event.get_plaintext().strip()))


def _content_prompt(
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
) -> Prompt[_NewContentAction]:
    if layout.focused_category is not None:
        return _focused_content_prompt(snapshot, layout)

    choices: list[PromptItem[_NewContentAction]] = []
    root_positions = {
        category: position for position, category in enumerate(layout.root_categories)
    }
    for category in layout.display_categories:
        code = chr(ord("a") + root_positions[category])
        items = snapshot.items_for(category)
        expanded = category in layout.expanded_categories
        choices.append(
            PromptItem(
                f"{'▼' if expanded else '▶'} {CATEGORY_NAMES[category]}",
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
                is_visible=expanded,
            )
            for index, item in enumerate(items, start=1)
        )
    return Prompt(
        title="🆕【新增内容】输入编号查看详情：",
        items=choices,
    )


def _focused_content_prompt(
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
) -> Prompt[_NewContentAction]:
    category = layout.focused_category
    if category is None:
        msg = "focused new-content prompt requires a category"
        raise ValueError(msg)
    root_positions = {
        current: position for position, current in enumerate(layout.root_categories)
    }
    code = chr(ord("a") + root_positions[category])
    choices = [
        PromptItem(
            item.name,
            _item_description(item),
            _NewContentAction("item", category, item),
            key=f"{code}{index}",
        )
        for index, item in enumerate(snapshot.items_for(category), start=1)
    ]
    return Prompt(
        title=f"🆕【{CATEGORY_NAMES[category]}】输入编号查看详情：",
        items=choices,
    )


def _focus_new_content_category(
    layout: _NewContentMenuLayout,
    category: NewContentCategory,
) -> _NewContentMenuLayout:
    return replace(
        layout,
        display_categories=(category,),
        expanded_categories=layout.expanded_categories | {category},
        focused_category=category,
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
        suffix = f"｜{names}" if names else ""
        return f"{change}｜{item.entity_id}{suffix}"
    if item.category in {"autocard_card", "autocard_role"}:
        kind = "角色" if item.category == "autocard_role" else "卡牌"
        return f"{change}｜{item.entity_id}｜{kind}"
    if item.category == "autocard_sanctuary_effect":
        sanctuary = str(item.payload.get("sanctuary_name", "")).strip()
        if not sanctuary:
            sanctuary = f"圣域 {int(item.payload.get('sanctuary_id', 0))}"
        pet_name = str(item.payload.get("sanctuary_pet_name", "")).strip()
        pet = f"｜精灵王：{pet_name}" if pet_name else ""
        unlock_round = int(item.payload.get("unlock_round", 0))
        phase = "基础圣域" if unlock_round == 0 else f"第 {unlock_round} 回合祝印"
        return f"{change}｜{sanctuary}{pet}｜{phase}"
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
        layout = matcher.state.get(NEW_CONTENT_MENU_LAYOUT_KEY)
        if not isinstance(layout, _NewContentMenuLayout):
            await matcher.finish("新增内容会话已失效，请重新发送指令。")
            return
        layout = _focus_new_content_category(layout, action.category)
        matcher.state[NEW_CONTENT_MENU_LAYOUT_KEY] = layout
        await _replace_prompt(
            matcher,
            event,
            _content_prompt(snapshot, layout),
        )
        return
    if action.item is not None:
        await _send_item_detail(action.item, matcher, event)


async def _replace_prompt(
    matcher: Matcher,
    event: Event,
    prompt: Prompt[_NewContentAction],
) -> None:
    matcher.state[PROMPT_STATE_KEY] = prompt
    send_result = await matcher.send(prompt.build_event_message(event))
    update_queued_menu_anchor(matcher, event, send_result)


async def _send_item_detail(
    item: NewContentItem,
    matcher: Matcher,
    event: Event,
) -> None:
    if item.category == "autocard_sanctuary_effect":
        await MessageFactory(_autocard_sanctuary_effect_detail(item)).send(
            at_sender=isinstance(event, GroupMessageEvent)
        )
        return
    services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
    if not isinstance(services, _NewContentServices):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    if item.category == "achievement":
        await MessageFactory(_achievement_detail(item)).send(
            at_sender=isinstance(event, GroupMessageEvent)
        )
        return
    if item.category == "skill":
        await MessageFactory(_skill_detail(item)).send(
            at_sender=isinstance(event, GroupMessageEvent)
        )
        return
    try:
        if item.category in {"autocard_card", "autocard_role"}:
            await _send_autocard_detail(item, services.autocard, event)
            return
        result = await _select_standard_item(item, services)
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if result.message:
        await MessageFactory(result.message).send(
            at_sender=isinstance(event, GroupMessageEvent)
        )
    elif result.reply is not None:
        await build_reply(result.reply).send(
            at_sender=isinstance(event, GroupMessageEvent)
        )


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


async def _send_autocard_detail(
    item: NewContentItem,
    service: Any,
    event: Event,
) -> None:
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
    await message.send(at_sender=isinstance(event, GroupMessageEvent))


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


def _skill_detail(item: NewContentItem) -> str:
    payload = item.payload
    change = "修改" if item.change_kind == "modified" else "新增"
    lines = [
        f"⚔️【{item.name}】",
        f"状态：{change}",
        f"🆔：{item.entity_id}",
    ]
    lines.extend(_skill_stat_lines(payload))
    if description := str(payload.get("info", "")).strip():
        lines.append(f"效果：{description}")
    if related := _skill_related_pets(payload.get("pets")):
        lines.append(f"关联精灵：{related}")
    return "\n".join(lines)


def _skill_stat_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    power = int(payload.get("power", 0))
    max_pp = int(payload.get("max_pp", 0))
    if power or max_pp:
        lines.append(f"威力：{power}｜PP：{max_pp}")
    if bool(payload.get("must_hit", False)):
        lines.append("命中：必中")
    elif (accuracy := int(payload.get("accuracy", 0))) > 0:
        lines.append(f"命中：{accuracy}%")
    if (crit_rate := int(payload.get("crit_rate", 0))) > 0:
        lines.append(f"暴击率：{crit_rate}%")
    if (priority := int(payload.get("priority", 0))) != 0:
        lines.append(f"先制：{priority:+d}")
    if (atk_num := int(payload.get("atk_num", 0))) > 1:
        lines.append(f"攻击次数：{atk_num}")
    return lines


def _skill_related_pets(value: object) -> str:
    if not isinstance(value, list):
        return ""
    related: list[str] = []
    for pet in value:
        if not isinstance(pet, dict):
            continue
        name = str(pet.get("name", "")).strip() or "未命名精灵"
        pet_id = int(pet.get("id", 0))
        label = _skill_pet_label(pet)
        suffix = f"（{pet_id}）" if pet_id else ""
        related.append(f"{name}{suffix}{label}")
    return "、".join(related)


def _skill_pet_label(pet: dict[str, Any]) -> str:
    if bool(pet.get("is_fifth", False)):
        return "（第五技能）"
    if bool(pet.get("is_advanced", False)):
        return "（强化技能）"
    if bool(pet.get("is_special", False)):
        return "（特殊技能）"
    if (level := int(pet.get("learning_level", 0))) > 0:
        return f"（Lv.{level}）"
    return ""


def _autocard_sanctuary_effect_detail(item: NewContentItem) -> str:
    payload = item.payload
    sanctuary_name = str(payload.get("sanctuary_name", "")).strip()
    sanctuary_id = int(payload.get("sanctuary_id", 0))
    sanctuary = sanctuary_name or f"圣域 {sanctuary_id}"
    unlock_round = int(payload.get("unlock_round", 0))
    change = "修改" if item.change_kind == "modified" else "新增"
    phase = "基础圣域" if unlock_round == 0 else f"第 {unlock_round} 回合祝印"
    lines = [
        f"🃏【{item.name}】",
        f"状态：{change}",
        f"圣域：{sanctuary}",
        f"阶段：{phase}",
    ]
    pet_name = str(payload.get("sanctuary_pet_name", "")).strip()
    pet_id = int(payload.get("sanctuary_pet_id", 0))
    if pet_name or pet_id:
        pet = pet_name or "未命名精灵王"
        suffix = f"（{pet_id}）" if pet_id else ""
        lines.append(f"关联精灵王：{pet}{suffix}")
    buff_id = str(payload.get("buff_id", "")).strip()
    buff_param = str(payload.get("buff_param", "")).strip()
    if buff_id:
        buff = buff_id if not buff_param else f"{buff_id}（参数：{buff_param}）"
        lines.append(f"关联 Buff：{buff}")
    description = str(payload.get("description", "")).strip()
    if description:
        lines.append(f"效果：{description}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _NewContentServices:
    pet: Any
    mintmark: Any
    equipment: Any
    autocard: Any
