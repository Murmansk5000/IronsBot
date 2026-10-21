# SPDX-License-Identifier: MIT
"""Fallback hint for an unclaimed direct mention."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,  # noqa: TC002 - NoneBot resolves handler annotations
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.context import command_context
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_operation_handler,
)
from ironsbot.integrations.onebot.rules import bot_mention
from ironsbot.services.ai.fallback_operations import addressed_hint

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService

__plugin_meta__ = PluginMetadata(
    name="寻址提示",
    description="用户直接提及机器人但未命中命令或 AI 时给出简短提示。",
    usage="由未认领的直接提及触发，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def _should_offer_hint(
    input_routing: AiInputRoutingService,
    event: GroupMessageEvent,
) -> bool:
    return input_routing.decide(
        message_input_context(event),
        command_context(event),
    ).offer_addressed_hint


def install(
    registry: MatcherFactory,
    input_routing: AiInputRoutingService,
    addressed_input_hints: AddressedInputHintService,
) -> None:
    async def operation(text: str, context: MessageInputContext):
        del text
        return addressed_hint(addressed_input_hints, input_routing, context)

    matcher = registry.on_message(
        policy=CommandPolicy.exempt("unclaimed direct mention hint"),
        rule=bot_mention()
        & Rule(lambda event: _should_offer_hint(input_routing, event)),
        priority=registry.priority("ai_chat"),
        block=True,
    )
    matcher.append_handler(make_portable_operation_handler(operation))


def plugin_contribution(
    *,
    input_routing: AiInputRoutingService,
    addressed_input_hints: AddressedInputHintService,
) -> PluginContribution:
    return PluginContribution(
        id="addressed_input_hint",
        install=partial(
            install,
            input_routing=input_routing,
            addressed_input_hints=addressed_input_hints,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            input_routing=context.resources.ai_input_routing,
            addressed_input_hints=context.resources.addressed_input_hints,
        ),
    )
