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
    begin_event_reply_conversation,
    enter_event_reply_conversation,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.replies import (
    send_portable_event_reply,
)
from ironsbot.services.portable_reply import as_portable_reply, deliver_reply_stages
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.semantic_requests import ActionDefinition, SemanticRequest
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, PortableReply

_PORTABLE_QUERY_NAMESPACE = "portable_query"
PortableQueryHandler = Callable[["Matcher", "T_State", "Event"], Awaitable[None]]


def make_portable_query_handler(
    operation: PortableOperation,
    sessions: PortableQuerySessions,
    action: ActionDefinition,
) -> PortableQueryHandler:
    """Adapt one shared query operation without duplicating its menu state."""

    return _OneBotPortableQueryAdapter(operation, sessions, action).handle


@dataclass(slots=True)
class _OneBotPortableQueryAdapter:
    operation: PortableOperation
    sessions: PortableQuerySessions
    action: ActionDefinition

    def semantic_request(
        self, event: MessageEvent, _state: T_State
    ) -> SemanticRequest | None:
        context = message_input_context(event)
        return self.sessions.semantic_request(
            context.text,
            context,
            action=self.action,
        )

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
            self.sessions.cancel(context)
            raise FinishedException
        if result is None:
            raise FinishedException
        await _deliver(matcher, event, result)
        if self.sessions.has_pending(context):
            await enter_event_reply_conversation(
                matcher,
                event,
                namespace=_PORTABLE_QUERY_NAMESPACE,
                handlers=[self.resolve_selection],
                reply_check=self.session_response,
                queue_semantic_request_resolver=self.semantic_request,
            )

    async def handle(
        self,
        matcher: Matcher,
        _state: T_State,
        event: Event,
    ) -> None:
        if not isinstance(event, MessageEvent):
            raise FinishedException
        context = message_input_context(event)
        self.sessions.cancel(context)
        await begin_event_reply_conversation(
            matcher,
            event,
            namespace=_PORTABLE_QUERY_NAMESPACE,
            handlers=[self.resolve_selection],
            pending_reply_check=_is_digit_selection_input,
            reply_check=self.session_response,
            queue_semantic_request_resolver=self.semantic_request,
        )
        try:
            result = await self.operation(context.text, context)
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if queued_conversation_is_cancelled(matcher):
            self.sessions.cancel(context)
            raise FinishedException
        if not self.sessions.has_pending(context):
            await _deliver(matcher, event, result)
            return
        reply = as_portable_reply(result)
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
            queue_semantic_request_resolver=self.semantic_request,
        )


async def _deliver(
    matcher: Matcher,
    event: MessageEvent,
    result: OutboundMessage | PortableReply | str,
) -> None:
    await deliver_reply_stages(
        lambda message: send_portable_event_reply(matcher, event, message),
        message_input_context(event).message,
        as_portable_reply(result),
    )


def _is_digit_selection_input(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()
