# SPDX-License-Identifier: GPL-3.0-or-later
"""Feature routing and peak-pool dispatch for the new-content menu."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_query_commands import (
    PEAK_ENVIRONMENT_CHANGES_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.new_content import (
    NEW_CONTENT_CATEGORIES,
    PEAK_POOL_NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentIndexUnavailableError,
    NewContentSnapshot,
    new_content_category_unavailable_message,
    new_content_unavailable_message,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.resources import NewContentMenuRenderer

from ..group import SeerMatcherGroup, seer_feature_rule

logger = logging.getLogger(__name__)


_REQUIRED_FEATURES: dict[NewContentCategory, str | None] = {
    "pet": "seer_pet",
    "pet_skin": "seer_pet",
    "skill": "seer_pet",
    "mintmark": "seer_mintmark",
    "suit": "seer_equipment",
    "equip": "seer_equipment",
    "mount": "seer_equipment",
    "achievement": None,
    "peak_pool": "seer_peak",
    "peak_expert_pool": "seer_peak",
    "autocard_card": "seer_autocard",
    "autocard_role": "seer_autocard",
    "autocard_sanctuary_effect": "seer_autocard",
}


@dataclass(frozen=True, slots=True)
class PeakPoolChangeRequest:
    categories: tuple[NewContentCategory, ...]
    title: str


def available_new_content_categories(
    group: SeerMatcherGroup,
    event: Event,
) -> tuple[NewContentCategory, ...]:
    from ironsbot.runtime.feature_policy import event_is_feature_allowed

    return tuple(
        category
        for category in NEW_CONTENT_CATEGORIES
        if (required_feature := _REQUIRED_FEATURES[category]) is None
        or event_is_feature_allowed(group.features, event, required_feature)
    )


def visible_new_content_categories(
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
) -> tuple[NewContentCategory, ...]:
    return tuple(category for category in categories if snapshot.items_for(category))


async def send_peak_pool(
    peak: Any,
    references: Any,
    matcher: Matcher,
    *,
    expert: bool,
) -> None:
    async def report_progress(message: str) -> None:
        await matcher.send(message)

    try:
        result = await peak.pool(expert=expert, progress=report_progress)
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if result.message:
        await matcher.finish(result.message)
        return
    if result.text:
        await matcher.finish(references.append(result.text, result.reference))
        return
    if result.image is not None:
        message = MessageFactory(Image(result.image))
        if url := references.url_for(result.reference):
            message += f"\n相关查询：{url}"
        await message.finish(at_sender=False)


def new_content_rendering_notice(event: Event) -> str | Message:
    text = "⏳ 正在生成新增内容图片，请稍候。"
    if not isinstance(event, GroupMessageEvent):
        return text
    return MessageSegment.at(event.user_id) + MessageSegment.text(f" {text}")


async def send_peak_pool_changes(
    snapshot: NewContentSnapshot,
    request: PeakPoolChangeRequest,
    menu_renderer: NewContentMenuRenderer,
    matcher: Matcher,
    event: Event,
) -> None:
    """Render weekly pool deltas without querying the current pool state."""

    await matcher.send(new_content_rendering_notice(event))
    try:
        image = await menu_renderer(
            snapshot,
            request.categories,
            None,
            request.title,
            frozenset(),
            0,
        )
    except Exception:
        logger.exception(
            "peak pool change rendering failed: categories=%s",
            request.categories,
        )
        await matcher.finish("❌ 生成巅峰环境变化图片失败，请稍后再试。")
        return
    await MessageFactory(Image(image)).finish(
        at_sender=isinstance(event, GroupMessageEvent)
    )


async def send_peak_pool_change_command(
    service: SeerDataQueryService,
    request: PeakPoolChangeRequest,
    group: SeerMatcherGroup,
    matcher: Matcher,
    event: Event,
) -> None:
    """Send weekly peak-pool deltas for a direct command."""

    try:
        snapshot = service.new_content_snapshot()
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    except NewContentIndexUnavailableError:
        await matcher.finish(new_content_unavailable_message())
        return

    available = available_new_content_categories(group, event)
    if not set(request.categories).issubset(available):
        await matcher.finish("当前会话未开放此新增内容分类。")
        return
    unavailable_categories: tuple[NewContentCategory, ...] = tuple(
        category
        for category in request.categories
        if not snapshot.is_category_comparable(category)
    )
    if unavailable_categories:
        await matcher.finish(
            new_content_category_unavailable_message(
                snapshot,
                unavailable_categories,
            )
        )
        return
    await send_peak_pool_changes(
        snapshot,
        request,
        group.resources.new_content_menu,
        matcher,
        event,
    )


def install_peak_environment_change_commands(
    group: SeerMatcherGroup,
    service: SeerDataQueryService,
    root_rule: Any,
) -> None:
    request = PeakPoolChangeRequest(
        PEAK_POOL_NEW_CONTENT_CATEGORIES,
        "巅峰环境变化",
    )
    command_id = "seer.data.peak_environment_changes"
    matcher = group.on_fullmatch(
        PEAK_ENVIRONMENT_CHANGES_COMMANDS,
        policy=CommandPolicy.command(command_id, help_ids=(command_id,)),
        rule=root_rule & seer_feature_rule(group.features, "seer_peak"),
        priority=group.matcher_priority("seer_data"),
    )
    matcher.append_handler(
        bind_async(
            send_peak_pool_change_command,
            service,
            request,
            group,
        )
    )
