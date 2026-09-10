# SPDX-License-Identifier: GPL-3.0-or-later
"""Feature routing and peak-pool dispatch for the new-content menu."""

from __future__ import annotations

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
    NewContentSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data_queries import SeerDataQueryService
from ..group import SeerMatcherGroup, seer_feature_rule

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
    "peak_master_pool": "seer_peak",
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
    master: bool = False,
) -> None:
    async def report_progress(message: str) -> None:
        await matcher.send(message)

    try:
        result = await peak.pool(expert=expert, progress=report_progress, master=master)
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


def install_peak_environment_change_commands(
    group: SeerMatcherGroup,
    service: SeerDataQueryService,
    root_rule: Any,
    start_new_content: Callable[..., Awaitable[None]],
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
            start_new_content,
            service,
            request.categories,
            group,
            root_title=request.title,
        )
    )
