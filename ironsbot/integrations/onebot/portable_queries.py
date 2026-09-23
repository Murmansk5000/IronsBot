# SPDX-License-Identifier: MIT
"""OneBot transport for the shared, account-scoped menu coordinator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves annotations
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves annotations
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves annotations

from ironsbot.integrations.onebot.conversations import is_self_message_event
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.prompt_sessions import (
    COMMAND_COOLDOWN_TOKEN_STATE_KEY,
    IN_FLIGHT_REQUEST_TOKEN_STATE_KEY,
)
from ironsbot.integrations.onebot.replies import send_portable_event_reply
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, PortableReply

PortableQueryHandler = Callable[["Matcher", "T_State", "Event"], Awaitable[None]]


def release_query_menu_admission(
    matcher: Matcher, sessions: PortableQuerySessions
) -> None:
    """Searching for choices is not a second charge for the selected query."""
    for service, key in (
        (sessions.interactions.cooldown, COMMAND_COOLDOWN_TOKEN_STATE_KEY),
        (sessions.interactions.request_service, IN_FLIGHT_REQUEST_TOKEN_STATE_KEY),
    ):
        token = matcher.state.pop(key, None)
        if service is not None and token is not None:
            service.release(token)


def make_portable_query_handler(
    operation: PortableOperation,
    sessions: PortableQuerySessions,
) -> PortableQueryHandler:
    async def handle(matcher: Matcher, _state: T_State, event: Event) -> None:
        if not isinstance(event, MessageEvent) or is_self_message_event(event):
            raise FinishedException
        context = message_input_context(event)
        try:
            reply = await sessions.interactions.execute(
                operation, context.text, context
            )
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if reply is not None:
            await _deliver(matcher, event, reply, sessions)

    return handle


def install_portable_menu_router(
    factory: MatcherFactory,
    sessions: PortableQuerySessions,
    features: FeatureService,
) -> None:
    """Permanent rules see the live store, not matcher-default state."""
    from ironsbot.integrations.onebot.matchers import CommandPolicy

    factory.close_portable_session = lambda event: sessions.discard(
        message_input_context(event)
    )
    sessions.interactions.request_service = factory.in_flight_requests
    sessions.interactions.cooldown = factory.cooldown

    async def matches(event: Event) -> bool:
        if not isinstance(event, MessageEvent) or is_self_message_event(event):
            return False
        context = message_input_context(event)
        return not features.is_message_blocked(
            context.message.actor, context.message.conversation
        ) and sessions.recognizes_response(context.text, context)

    async def handle(matcher: Matcher, event: Event) -> None:
        if not isinstance(event, MessageEvent):
            return
        context = message_input_context(event)
        try:
            reply = await sessions.interactions.select(context.text, context)
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if reply is not None:
            await _deliver(matcher, event, reply, sessions)

    matcher = factory.on_message(
        policy=CommandPolicy.exempt("portable menu input"),
        rule=Rule(matches),
        priority=-31,
        block=True,
    )
    matcher.append_handler(handle)


async def _deliver(
    matcher: Matcher,
    event: MessageEvent,
    reply: PortableReply,
    sessions: PortableQuerySessions,
) -> bool:
    context = message_input_context(event)

    async def send(message: OutboundMessage) -> SendResult:
        result = await send_portable_event_reply(matcher, event, message)
        sessions.record_delivery(context, message, result)
        return result

    return await deliver_portable_reply(reply, send)
