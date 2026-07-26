# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import CommandPolicy, bind_async
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data_queries import (
        DataQueryReply,
        SeerDataQueryService,
    )


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
        ("下周预告", "seer_data_preview", service.weekly_preview),
        ("数据版本", "seer_data_version", service.data_version),
        (
            ("新增成就", "新成就"),
            "seer_data_new_achievements",
            service.new_achievements,
        ),
        (
            ("赛季倒计时", "赛季时间", "赛季结束", "赛季"),
            "seer_season_countdown",
            service.season_countdown,
        ),
    )
    rule = seer_feature_rule(group.features, "seer_data") & no_reply()
    for messages, command_id, operation in commands:
        matcher = group.on_fullmatch(
            messages,
            policy=CommandPolicy.command(command_id),
            rule=rule,
            priority=group.matcher_priority("seer_data"),
        )
        matcher.append_handler(bind_async(_finish_query, operation))
