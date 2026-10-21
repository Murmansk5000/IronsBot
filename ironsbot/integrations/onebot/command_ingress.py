# SPDX-License-Identifier: MIT
"""OneBot event conversion and receipts for the shared command runtime."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - runtime dependency injection
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - runtime dependency injection
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - runtime dependency injection

from ironsbot.integrations.onebot.conversations import is_self_message_event
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.portable_commands import PortableCommandRouter

_CONTEXT_KEY = "_ironsbot_message_input"


def install_command_ingress(
    factory: MatcherFactory,
    router: PortableCommandRouter,
    messenger: OneBotOutboundMessenger,
) -> None:
    def accepts(bot: Bot, event: Event, state: T_State) -> bool:
        if not isinstance(event, MessageEvent) or is_self_message_event(event):
            return False
        context = message_input_context(event)
        if context.request_bot_id != bot.self_id:
            return False
        state[_CONTEXT_KEY] = context
        return True

    async def handle(matcher: Matcher, bot: Bot, event: Event, state: T_State) -> None:
        if not isinstance(event, MessageEvent):
            return
        context = state.pop(_CONTEXT_KEY)

        if await router.ingress.handle(
            context, partial(messenger.reply_from, bot, context)
        ):
            matcher.stop_propagation()

    matcher = factory.on_message(
        policy=CommandPolicy.exempt("shared command runtime"),
        rule=Rule(accepts),
        priority=-31,
        block=False,
    )
    matcher.append_handler(handle)
