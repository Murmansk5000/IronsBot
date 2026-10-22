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

from ironsbot.core.platform import Platform
from ironsbot.integrations.onebot.event_ingress import (
    ADMITTED_MESSAGE_KEY,
    AdmittedOneBotMessage,
)
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.portable_commands import PortableCommandRouter


def install_command_ingress(
    factory: MatcherFactory,
    router: PortableCommandRouter,
    messenger: OneBotOutboundMessenger,
) -> None:
    def accepts(bot: Bot, event: Event, state: T_State) -> bool:
        if not isinstance(event, MessageEvent):
            return False
        frame = state.get(ADMITTED_MESSAGE_KEY)
        return (
            isinstance(frame, AdmittedOneBotMessage)
            and frame.event is event
            and frame.context.message.platform is Platform.ONEBOT
            and frame.context.execution_identity is not None
            and frame.context.execution_identity.platform is Platform.ONEBOT
            and frame.context.request_bot_id == bot.self_id
            and frame.context.message.message_id == str(event.message_id)
            and frame.context.message.actor == onebot_actor_ref(event.user_id)
            and frame.context.message.conversation
            == onebot_conversation_ref(
                event.user_id, group_id=getattr(event, "group_id", None)
            )
        )

    async def handle(matcher: Matcher, bot: Bot, event: Event, state: T_State) -> None:
        if not isinstance(event, MessageEvent):
            return
        frame = state.pop(ADMITTED_MESSAGE_KEY)
        assert isinstance(frame, AdmittedOneBotMessage)
        context = frame.context

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
