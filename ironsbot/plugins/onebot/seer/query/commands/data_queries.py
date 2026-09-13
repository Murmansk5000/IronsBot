# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    bind_async,
)
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.external_references import SeerInfoReference

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data_queries import DataQueryReply, SeerDataQueryService
    from ironsbot.services.seer.external_references import SeerInfoReferences


async def _finish_query(
    operation: Callable[[], Awaitable[DataQueryReply]],
    *,
    matcher: Matcher,
    references: SeerInfoReferences | None,
    reference: SeerInfoReference | None = None,
) -> None:
    try:
        reply: DataQueryReply = await operation()
    except DataUnavailableError:
        await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
        return
    if isinstance(reply, (bytes, DataQueryImageReply)):
        image = reply if isinstance(reply, bytes) else reply.image
        message = Message(MessageSegment.image(image))
        if isinstance(reply, DataQueryImageReply) and reply.notice:
            message += MessageSegment.text(f"\n{reply.notice}")
        if references is not None and (url := references.url_for(reference)):
            message += MessageSegment.text(f"\n相关查询：{url}")
        await matcher.finish(message)
        return
    await matcher.finish(reply)


def install(group: SeerMatcherGroup) -> None:
    service: SeerDataQueryService = group.resources.data_queries
    references = getattr(group.resources, "external_references", None)
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
