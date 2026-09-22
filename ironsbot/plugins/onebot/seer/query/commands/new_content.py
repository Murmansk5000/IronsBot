# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot adapters for release content selection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters import (
    Event,  # noqa: TC002 - NoneBot resolves callback annotations
)
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import (
    T_State,  # noqa: TC002 - NoneBot resolves callback annotations
)

from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    bind_async,
    update_queued_menu_anchor,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.prompts import (
    PROMPT_STATE_KEY,
    Prompt,
    PromptItem,
    enter_prompt,
)
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.seer.autocard import AutocardEntry
from ironsbot.services.seer.data import (
    DataPublicationChangedError,
    DataUnavailableError,
)
from ironsbot.services.seer.data_query_commands import (
    NEW_CONTENT_COMMAND_SPECS,
    NEW_CONTENT_COMMANDS,
    available_new_content_categories,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.new_content import (
    NewContentCategory,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentSnapshot,
    NewContentSnapshotChangedError,
    new_content_unavailable_message,
)
from ironsbot.services.seer.new_content_menu import (
    NewContentAction,
    NewContentMenuLayout,
    build_new_content_menu,
    focus_new_content_category,
    plan_new_content_menu,
)
from ironsbot.services.seer.query_result import QueryReply

from ..group import SeerMatcherGroup, seer_feature_rule
from ..query_conversation import send_query_reply

if TYPE_CHECKING:
    from ironsbot.services.seer.autocard_media import AutocardMediaService
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.new_content_details import NewContentDetailService
    from ironsbot.services.seer.resources import NewContentMenuRenderer


NEW_CONTENT_SNAPSHOT_KEY = "new_content_snapshot"
NEW_CONTENT_SERVICES_KEY = "new_content_services"
NEW_CONTENT_MENU_LAYOUT_KEY = "new_content_menu_layout"
logger = logging.getLogger(__name__)


_NEW_CONTENT_INPUT_PATTERN = re.compile(
    r"(?:[a-z](?:[1-9]\d*)?|[1-9]\d*|0)",
    re.IGNORECASE,
)


def install(group: SeerMatcherGroup) -> None:
    service: SeerDataQueryService = group.resources.data_queries
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

    for spec in NEW_CONTENT_COMMAND_SPECS:
        rule = root_rule
        for feature in spec.required_features:
            rule = rule & seer_feature_rule(group.features, feature)
        matcher = group.on_fullmatch(
            spec.commands,
            policy=CommandPolicy.command(
                spec.command_id,
                help_ids=(spec.command_id,),
            ),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(
            bind_async(_start_new_content, service, spec.categories, group)
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

    layout = plan_new_content_menu(
        snapshot,
        _available_categories(group, event),
        categories,
        expanded_categories=group.new_content_expanded_categories,
        preview_max_items=group.new_content_preview_max_items,
    )
    if isinstance(layout, str):
        await matcher.finish(layout)
        return
    prompt = _content_prompt(snapshot, layout)
    state[NEW_CONTENT_SNAPSHOT_KEY] = snapshot
    state[NEW_CONTENT_SERVICES_KEY] = _NewContentServices(
        details=group.resources.new_content_details,
        menu_renderer=group.resources.new_content_menu,
        autocard_media=group.resources.autocard_media,
    )
    state[NEW_CONTENT_MENU_LAYOUT_KEY] = layout
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_new_content_selection,
        _is_new_content_input,
        prompt_message=_render_content_prompt(
            prompt,
            snapshot,
            layout,
            group.resources.new_content_menu,
            event,
        ),
    )


def _available_categories(
    group: SeerMatcherGroup,
    event: Event,
) -> tuple[NewContentCategory, ...]:
    from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed

    return available_new_content_categories(
        lambda feature: event_is_feature_allowed(group.features, event, feature)
    )


def _is_new_content_input(event: Event) -> bool:
    return bool(_NEW_CONTENT_INPUT_PATTERN.fullmatch(event.get_plaintext().strip()))


def _content_prompt(
    snapshot: NewContentSnapshot,
    layout: NewContentMenuLayout,
) -> Prompt[NewContentAction]:
    menu = build_new_content_menu(snapshot, layout)
    return Prompt(
        title=menu.title,
        items=[
            PromptItem(choice.name, choice.description, choice.action, key=choice.key)
            for choice in menu.choices
        ],
    )


async def _resolve_new_content_selection(
    selection: PromptItem[NewContentAction],
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
        if not isinstance(layout, NewContentMenuLayout):
            await matcher.finish("新增内容会话已失效，请重新发送指令。")
            return
        layout = focus_new_content_category(layout, action.category)
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
    prompt: Prompt[NewContentAction],
) -> None:
    matcher.state[PROMPT_STATE_KEY] = prompt
    snapshot = matcher.state.get(NEW_CONTENT_SNAPSHOT_KEY)
    layout = matcher.state.get(NEW_CONTENT_MENU_LAYOUT_KEY)
    services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
    if (
        not isinstance(snapshot, NewContentSnapshot)
        or not isinstance(layout, NewContentMenuLayout)
        or not isinstance(services, _NewContentServices)
    ):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    send_result = await matcher.send(
        await _render_content_prompt(
            prompt,
            snapshot,
            layout,
            services.menu_renderer,
            event,
        )
    )
    update_queued_menu_anchor(matcher, event, send_result)


async def _render_content_prompt(
    prompt: Prompt[NewContentAction],
    snapshot: NewContentSnapshot,
    layout: NewContentMenuLayout,
    renderer: NewContentMenuRenderer,
    event: Event,
) -> str | Message:
    """Render only this menu as an image; preserve text as a resilient fallback."""

    try:
        image = await renderer(
            snapshot,
            layout.display_categories,
            layout.focused_category,
            "新增内容",
            layout.expanded_categories,
            layout.preview_max_items,
        )
    except NewContentSnapshotChangedError:
        return prompt.build_event_message(event)
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
    services = matcher.state.get(NEW_CONTENT_SERVICES_KEY)
    snapshot = matcher.state.get(NEW_CONTENT_SNAPSHOT_KEY)
    if not isinstance(services, _NewContentServices) or not isinstance(
        snapshot, NewContentSnapshot
    ):
        await matcher.finish("新增内容会话已失效，请重新发送指令。")
        return
    try:
        detail = await services.details.select(
            snapshot,
            item,
            execution_identity=message_input_context(event).execution_identity,
        )
    except (NewContentSnapshotChangedError, DataPublicationChangedError):
        await matcher.finish("数据已更新，当前新增内容菜单已失效，重新发送指令查看。")
        return
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if detail is None:
        return
    if isinstance(detail, QueryReply):
        await send_query_reply(detail, event, finish=False)
        return
    if isinstance(detail, AutocardEntry):
        message = render_onebot_outbound_message(
            await services.autocard_media.outbound(
                detail,
                include_additional_images=False,
            )
        )
    else:
        message = Message(detail)
    await matcher.send(message, at_sender=isinstance(event, GroupMessageEvent))


@dataclass(frozen=True, slots=True)
class _NewContentServices:
    details: NewContentDetailService
    menu_renderer: NewContentMenuRenderer
    autocard_media: AutocardMediaService
