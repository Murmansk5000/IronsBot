# SPDX-License-Identifier: MIT
"""OneBot event conversion and receipts for the shared command runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - runtime dependency injection
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - runtime dependency injection
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - runtime dependency injection

from ironsbot.integrations.onebot.conversations import is_self_message_event
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import send_portable_event_reply

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.portable_commands import PortableCommandRouter

_CONTEXT_KEY = "_ironsbot_message_input"


def install_command_ingress(
    factory: MatcherFactory, router: PortableCommandRouter
) -> None:
    def accepts(event: Event, state: T_State) -> bool:
        if not isinstance(event, MessageEvent) or is_self_message_event(event):
            return False
        context = message_input_context(event)
        state[_CONTEXT_KEY] = context
        return True

    async def handle(matcher: Matcher, event: Event, state: T_State) -> None:
        if not isinstance(event, MessageEvent):
            return
        context = state.pop(_CONTEXT_KEY)

        async def send(message: OutboundMessage) -> SendResult:
            return await send_portable_event_reply(matcher, event, message)

        if await router.ingress.handle(context, send):
            matcher.stop_propagation()

    matcher = factory.on_message(
        policy=CommandPolicy.exempt("shared command runtime"),
        rule=Rule(accepts),
        priority=-31,
        block=False,
    )
    matcher.append_handler(handle)
