# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from nonebot.adapters import (
    Event,  # noqa: TC002 - NoneBot resolves callback annotations
)
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
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
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.seer.autocard import AutocardPromptValue
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
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
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    CATEGORY_NAMES,
    PEAK_POOL_NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentSnapshot,
    format_new_content_category_count,
    format_new_content_item_description,
    new_content_category_preview_items,
    new_content_category_unavailable_message,
    new_content_unavailable_message,
)
from ironsbot.services.seer.pet_query import PetImageSelection

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import build_reply
from .new_content_routing import (
    available_new_content_categories,
    send_peak_pool,
    visible_new_content_categories,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data_queries import (
        DataQueryReply,
        SeerDataQueryService,
    )


NEW_CONTENT_SNAPSHOT_KEY = "new_content_snapshot"
NEW_CONTENT_SERVICES_KEY = "new_content_services"
NEW_CONTENT_MENU_LAYOUT_KEY = "new_content_menu_layout"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _NewContentAction:
    kind: str
    category: NewContentCategory | None = None
    item: NewContentItem | None = None


@dataclass(frozen=True, slots=True)
class _NewContentMenuLayout:
    """Keep stable root keys while optionally focusing one numeric child menu."""

    display_categories: tuple[NewContentCategory, ...]
    expanded_categories: frozenset[NewContentCategory] = frozenset()
    auto_expand_max_items: int = 5
    focused_category: NewContentCategory | None = None
    root_title: str | None = None


_NEW_CONTENT_INPUT_PATTERN = re.compile(r"(?:[a-z]|[1-9]\d*|0)", re.IGNORECASE)


async def _finish_query(
    operation: Callable[[], Awaitable[DataQueryReply]],
    *,
    matcher: Matcher,
    references: SeerInfoReferences,
    reference: SeerInfoReference | None = None,
) -> None:
    try:
        reply: DataQueryReply = await operation()
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if isinstance(reply, (bytes, DataQueryImageReply)):
        image = reply if isinstance(reply, bytes) else reply.image
        message = MessageFactory(Image(image))
        if isinstance(reply, DataQueryImageReply) and reply.notice:
            message += f"\n{reply.notice}"
        if url := references.url_for(reference):
            message += f"\n相关查询：{url}"
        await message.finish()
        return
    await matcher.finish(reply)


def install(group: SeerMatcherGroup) -> None:
    service: SeerDataQueryService = group.resources.data_queries
    references = group.resources.external_references
    commands = (
        (
            WEEKLY_PREVIEW_COMMANDS,
            "seer_data_preview",
            service.weekly_preview,
            SeerInfoReference.WEEKLY_PREVIEW,
        ),
        (DATA_VERSION_COMMANDS, "seer_data_version", service.data_version, None),
        (
            SEASON_COUNTDOWN_COMMANDS,
            "seer_season_countdown",
            service.season_countdown,
            None,
        ),
    )
    rule = seer_feature_rule(group.features, "seer_data") & explicit_command()
    for messages, command_id, operation, reference in commands:
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(
                command_id,
                help_ids=("seer.data.query",),
            ),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(
            bind_async(
                _finish_query,
                operation,
                references=references,
                reference=reference,
            )
        )

    _install_new_content_commands(group, service)


def _install_new_content_commands(
    group: SeerMatcherGroup,
    service: SeerDataQueryService,
) -> None:
    root_rule = seer_feature_rule(group.features, "seer_data") & explicit_command()
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

    available = available_new_content_categories(group, event)
    if categories is not None and not set(categories).issubset(available):
        await matcher.finish("当前会话未开放此新增内容分类。")
        return
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
    visible_categories = visible_new_content_categories(
        snapshot,
        comparable_categories,
    )
    if categories is not None and not visible_categories:
        await matcher.finish(_empty_new_content_message(snapshot, categories))
        return
    if not visible_categories:
        await matcher.finish("本周暂未检测到可验证的新增或修改内容。")
        return
    layout = _NewContentMenuLayout(
        display_categories=visible_categories,
        expanded_categories=frozenset(group.new_content_expanded_categories).intersection(
            visible_categories
        ),
        auto_expand_max_items=group.new_content_auto_expand_max_items,
        focused_category=(
            visible_categories[0] if len(visible_categories) == 1 else None
        ),
        root_title=(
            "新增群星牌"
            if categories == AUTOCARD_NEW_CONTENT_CATEGORIES
            else "新增内容"
        ),
    )
    prompt = _content_prompt(snapshot, layout)
    state[NEW_CONTENT_SNAPSHOT_KEY] = snapshot
    state[NEW_CONTENT_SERVICES_KEY] = _NewContentServices(
        pet=group.resources.pet_query,
        mintmark=group.resources.mintmark,
        equipment=group.resources.equipment,
        autocard=group.resources.autocard,
        peak=group.resources.peak_query,
        references=group.resources.external_references,
        menu_renderer=group.resources.new_content_menu,
    )
    state[NEW_CONTENT_MENU_LAYOUT_KEY] = layout
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_new_content_selection,
        _is_new_content_input,
        prompt_message=_render_content_prompt_with_notice(
            prompt,
            snapshot,
            layout,
            group.resources.new_content_menu,
            event,
            matcher,
        ),
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


def _is_new_content_input(event: Event) -> bool:
    return bool(_NEW_CONTENT_INPUT_PATTERN.fullmatch(event.get_plaintext().strip()))


def _content_prompt(
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
) -> Prompt[_NewContentAction]:
    if layout.focused_category is not None:
        return _focused_content_prompt(snapshot, layout)

    choices: list[PromptItem[_NewContentAction]] = []
    for index, category in enumerate(layout.display_categories):
        code = chr(ord("a") + index)
        items = snapshot.items_for(category)
        if category in PEAK_POOL_NEW_CONTENT_CATEGORIES:
            choices.append(
                PromptItem(
                    f"↗ {CATEGORY_NAMES[category]}",
                    f"{len(items)} 只变化",
                    _NewContentAction("pool", category),
                    key=code,
                )
            )
            continue
        expanded = (
            category in layout.expanded_categories
            and layout.auto_expand_max_items > 0
        )
        preview_items = (
            new_content_category_preview_items(
                snapshot,
                category,
                layout.auto_expand_max_items,
            )
            if expanded
            else ()
        )
        choices.append(
            PromptItem(
                f"{'▼' if expanded else '▶'} {CATEGORY_NAMES[category]}",
                format_new_content_category_count(items),
                _NewContentAction("category", category),
                key=code,
            )
        )
        for item_index, item in enumerate(preview_items, start=1):
            choices.append(
                PromptItem(
                    item.name,
                    _item_description(item),
                    _NewContentAction("item", category, item),
                    is_sub_prompt=True,
                    key=f"{code}{item_index}",
                    is_visible=expanded,
                )
            )
    return Prompt(
        title=f"🆕【{_new_content_root_title(layout)}】输入编号查看详情：",
        items=choices,
        page_id="new_content:root",
    )


def _new_content_root_title(layout: _NewContentMenuLayout) -> str:
    if layout.root_title:
        return layout.root_title
    if layout.display_categories == AUTOCARD_NEW_CONTENT_CATEGORIES:
        return "新增群星牌"
    return "新增内容"


def _new_content_menu_title(layout: _NewContentMenuLayout) -> str:
    if layout.focused_category is not None:
        return CATEGORY_NAMES[layout.focused_category]
    return _new_content_root_title(layout)


def _focused_content_prompt(
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
) -> Prompt[_NewContentAction]:
    category = layout.focused_category
    if category is None:
        msg = "focused new-content prompt requires a category"
        raise ValueError(msg)
    choices = [
        PromptItem(
            item.name,
            _item_description(item),
            _NewContentAction("item", category, item),
        )
        for item in snapshot.items_for(category)
    ]
    return Prompt(
        title=f"🆕【{CATEGORY_NAMES[category]}】输入编号查看详情：",
        items=choices,
        page_id=f"new_content:category:{category}",
    )


def _focus_new_content_category(
    layout: _NewContentMenuLayout,
    category: NewContentCategory,
) -> _NewContentMenuLayout:
    return replace(
        layout,
        focused_category=category,
    )


def _item_description(item: NewContentItem) -> str:
    return format_new_content_item_description(item)


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
    if action.kind == "pool" and action.category is not None:
        services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
        if not isinstance(services, _NewContentServices):
            await matcher.finish("新增内容会话已失效，请重新发送指令。")
            return
        await send_peak_pool(
            services.peak,
            services.references,
            matcher,
            expert=action.category == "peak_expert_pool",
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
    snapshot = matcher.state.get(NEW_CONTENT_SNAPSHOT_KEY)
    layout = matcher.state.get(NEW_CONTENT_MENU_LAYOUT_KEY)
    services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
    if not isinstance(snapshot, NewContentSnapshot) or not isinstance(
        layout, _NewContentMenuLayout
    ) or not isinstance(services, _NewContentServices):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    await matcher.send(_new_content_rendering_notice(event))
    send_result = await matcher.send(
        await _render_content_prompt(
            prompt,
            snapshot,
            layout,
            services.menu_renderer,
            event,
        )
    )
    update_queued_menu_anchor(
        matcher,
        event,
        send_result,
        page_id=prompt.page_id,
    )


async def _render_content_prompt_with_notice(  # noqa: PLR0913
    prompt: Prompt[_NewContentAction],
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
    renderer: Any,
    event: Event,
    matcher: Matcher,
) -> str | Message:
    await matcher.send(_new_content_rendering_notice(event))
    return await _render_content_prompt(prompt, snapshot, layout, renderer, event)


def _new_content_rendering_notice(event: Event) -> str | Message:
    text = "⏳ 正在生成新增内容图片，请稍候。"
    if not isinstance(event, GroupMessageEvent):
        return text
    return MessageSegment.at(event.user_id) + MessageSegment.text(f" {text}")


async def _render_content_prompt(
    prompt: Prompt[_NewContentAction],
    snapshot: NewContentSnapshot,
    layout: _NewContentMenuLayout,
    renderer: Any,
    event: Event,
) -> str | Message:
    """Render only this menu as an image; preserve text as a resilient fallback."""

    try:
        image = await renderer(
            snapshot,
            layout.display_categories,
            layout.focused_category,
            _new_content_menu_title(layout),
            layout.expanded_categories,
            layout.auto_expand_max_items,
        )
    except Exception:
        logger.exception("new content menu rendering failed; falling back to text")
        return prompt.build_event_message(event)

    message = Message()
    if isinstance(event, GroupMessageEvent):
        message += MessageSegment.at(event.user_id)
        message += MessageSegment.text(" ")
    message += MessageSegment.image(image)
    return message


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
    peak: Any
    references: Any
    menu_renderer: Any
