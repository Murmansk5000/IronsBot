# SPDX-License-Identifier: MIT
"""Run portable query sessions through OneBot's durable input queue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.integrations.onebot.conversations import (
    enter_event_reply_conversation,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.replies import send_portable_event_reply
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.data_queries import DataQueryImageReply

_PORTABLE_QUERY_NAMESPACE = "portable_query"
PortableQueryHandler = Callable[["Matcher", "T_State", "Event"], Awaitable[None]]


def make_portable_query_handler(
    operation: PortableOperation,
    sessions: PortableQuerySessions,
) -> PortableQueryHandler:
    return _OneBotPortableQueryAdapter(operation, sessions).handle


@dataclass(slots=True)
class _OneBotPortableQueryAdapter:
    operation: PortableOperation
    sessions: PortableQuerySessions

    def session_response(self, event: MessageEvent) -> bool:
        context = message_input_context(event)
        return self.sessions.recognizes_response(context.text, context)

    async def resolve_selection(
        self,
        matcher: Matcher,
        event: MessageEvent,
        _state: T_State,
    ) -> None:
        context = message_input_context(event)
        result = await self.sessions.select(
            context.text,
            context,
            allow_deferred=True,
        )
        if queued_conversation_is_cancelled(matcher):
            raise FinishedException
        if result is None:
            raise FinishedException
        await _deliver(matcher, event, result)
        await self._continue_pending_session(matcher, event, context)

    async def handle(
        self,
        matcher: Matcher,
        _state: T_State,
        event: Event,
    ) -> None:
        if not isinstance(event, MessageEvent):
            raise FinishedException
        context = message_input_context(event)
        try:
            result = await self.operation(context.text, context)
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if queued_conversation_is_cancelled(matcher):
            raise FinishedException
        if self.sessions.active_prompt(context) is None:
            await _deliver(matcher, event, result)
            return
        reply = _as_portable_reply(result)
        prompt = render_onebot_outbound_message(
            reply.message,
            conversation=context.message.conversation,
        )
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=_PORTABLE_QUERY_NAMESPACE,
            handlers=[self.resolve_selection],
            reply_check=self.session_response,
            prompt=prompt,
        )

    async def _continue_pending_session(
        self,
        matcher: Matcher,
        event: MessageEvent,
        context: MessageInputContext,
    ) -> None:
        if self.sessions.active_prompt(context) is None:
            return
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=_PORTABLE_QUERY_NAMESPACE,
            handlers=[self.resolve_selection],
            reply_check=self.session_response,
        )


async def _deliver(
    matcher: Matcher,
    event: MessageEvent,
    result: OutboundMessage | PortableReply | DataQueryImageReply | str,
) -> None:
    reply = _as_portable_reply(result)
    receipt = await send_portable_event_reply(matcher, event, reply.message)
    if not receipt.delivered:
        reply.delivery_failed()
        return
    reply.delivered()
    for message in reply.additional_messages:
        receipt = await send_portable_event_reply(matcher, event, message)
        if not receipt.delivered:
            return
    if reply.follow_up is not None:
        await _deliver(matcher, event, await reply.follow_up())


def _as_portable_reply(
    result: OutboundMessage | PortableReply | DataQueryImageReply | str,
) -> PortableReply:
    from ironsbot.services.seer.data_queries import DataQueryImageReply

    if isinstance(result, PortableReply):
        return result
    if isinstance(result, DataQueryImageReply):
        return PortableReply(result.to_outbound())
    if isinstance(result, str):
        from ironsbot.core.outbound import OutboundMessage

        return PortableReply(OutboundMessage.from_text(result))
    return PortableReply(result)
