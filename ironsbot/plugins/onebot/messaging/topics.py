# SPDX-License-Identifier: MIT
"""Native event adaptation for the shared topic service before portable routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves annotations
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves annotations

from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.replies import finish_matcher_message
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.messaging.topic_commands import (
    build_topic_operations,
    parse_topic_command,
    topic_command_contracts,
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.messaging.service import MessagingService


def install_topic_commands(
    registry: MatcherFactory, messaging: MessagingService
) -> None:
    service = messaging.topics
    if service is None:
        return

    def matches(event: GroupMessageEvent | PrivateMessageEvent) -> bool:
        return (
            parse_topic_command(message_input_context(event).text, service.known_keys)
            is not None
        )

    def command_id(event: MessageEvent, _state: T_State) -> str:
        parsed = parse_topic_command(
            message_input_context(event).text, service.known_keys
        )
        assert parsed is not None
        return f"messaging.topic.{parsed.action}"

    async def handle(
        matcher: Matcher, event: GroupMessageEvent | PrivateMessageEvent
    ) -> None:
        context = message_input_context(event)
        operations = build_topic_operations(
            service,
            group_role=event.sender.role
            if isinstance(event, GroupMessageEvent)
            else None,
        )
        result = await operations[command_id(event, {})](context.text, context)
        await finish_matcher_message(
            matcher, render_onebot_outbound_message(result), event=event
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            command_id,
            help_ids=tuple(item.id for item in topic_command_contracts(service)),
        ),
        rule=Rule(matches) & explicit_command(),
        priority=max(registry.priority("message_commands") - 1, 0),
        block=True,
    )
    matcher.append_handler(handle)
