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
from ironsbot.integrations.onebot.matcher_support import (
    bind_async,
    get_prompt_session_manager,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.prompt_sessions import (
    QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY,
)
from ironsbot.integrations.onebot.replies import send_portable_event_reply
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
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
        owner_context: MessageInputContext,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        context = message_input_context(event)
        if state.get(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY):
            get_prompt_session_manager(matcher).detach_queued_conversation(state)
            result = await self.sessions.select_shared(
                context.text,
                owner_context,
                context,
                allow_deferred=True,
            )
        else:
            result = await self.sessions.select(
                context.text,
                context,
                allow_deferred=True,
            )
        if queued_conversation_is_cancelled(matcher):
            raise FinishedException
        if result is None:
            raise FinishedException
        if await _deliver(matcher, event, result):
            await self._continue_pending_session(matcher, event, context)

    def shared_session_response(
        self,
        owner_context: MessageInputContext,
        event: MessageEvent,
    ) -> bool:
        context = message_input_context(event)
        return self.sessions.recognizes_shared_response(
            context.text,
            owner_context,
            context,
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
        try:
            result = await self.operation(context.text, context)
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if queued_conversation_is_cancelled(matcher):
            raise FinishedException
        if await _deliver(matcher, event, result):
            await self._continue_pending_session(matcher, event, context)

    async def _continue_pending_session(
        self,
        matcher: Matcher,
        event: MessageEvent,
        context: MessageInputContext,
    ) -> None:
        if not self.sessions.has_active_session(context):
            return
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=_PORTABLE_QUERY_NAMESPACE,
            handlers=[bind_async(self.resolve_selection, context)],
            reply_check=self.session_response,
            group_reply_check=lambda reply: self.shared_session_response(
                context, reply
            ),
            allow_group_reply_exit=True,
        )


async def _deliver(
    matcher: Matcher,
    event: MessageEvent,
    result: OutboundMessage | PortableReply | DataQueryImageReply | str,
) -> bool:
    return await deliver_portable_reply(
        _as_portable_reply(result),
        lambda message: send_portable_event_reply(matcher, event, message),
    )


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
