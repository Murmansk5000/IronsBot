# SPDX-License-Identifier: MIT
"""Execution path for inputs claimed by a queued prompt conversation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.runtime.onebot_context import event_request_scope
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY,
    QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY,
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    REQUEST_RESPONSE_TOKEN_STATE_KEY,
    PromptSessionManager,
    _QueuedConversation,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.runtime.semantic_requests import SemanticRequest

PromptSessionGetter = Callable[[T_State], PromptSessionManager]
CreateTemporaryMatcher = Callable[[Matcher, _QueuedConversation], Awaitable[None]]


async def capture_queued_conversation_input(  # noqa: C901, PLR0912, PLR0915
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    get_prompt_sessions: PromptSessionGetter,
    create_temporary_matcher: CreateTemporaryMatcher,
) -> None:
    prompt_sessions = get_prompt_sessions(state)
    context = prompt_sessions.queued_conversation(state)
    if context is None or not context.active or not isinstance(event, MessageEvent):
        raise FinishedException

    if not prompt_sessions.claim_input(event):
        logger.debug(
            "queued conversation input already claimed: namespace=%s "
            "session=%s user=%s message_id=%s",
            context.namespace,
            context.event_session_id,
            event.user_id,
            event.message_id,
        )
        raise FinishedException

    is_shared_group_reply = context.is_shared_group_reply(event)
    if event.get_plaintext().strip() == "0":
        if is_shared_group_reply and context.allow_group_reply_exit:
            await create_temporary_matcher(matcher, context)
            state.clear()
            state.update(context.state)
            state[QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY] = True
            return
        prompt_sessions.cancel_queued_conversation(state)
        if getattr(event, "group_id", None) is not None:
            await matcher.finish(
                OneBotMessageSegment.at(event.user_id)
                + OneBotMessageSegment.text(" 已退出当前选择。")
            )
        await matcher.finish("已退出当前选择。")

    pending = context.pending
    request: SemanticRequest | None = None
    request_token: object | None = None
    feedback: str | None = None
    if not pending:
        request, request_token, feedback = _admit_semantic_request(
            context,
            event,
            is_shared_group_reply=is_shared_group_reply,
        )
        if feedback is not None:
            await create_temporary_matcher(matcher, context)
            state[QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY] = True
            await _send_in_flight_feedback(matcher, event, feedback)
            raise FinishedException

    reservation = context.reserve(request_token)
    if reservation is None:
        raise FinishedException
    ticket, ready = reservation
    queued_at = monotonic()
    waited = not ready.done()
    activated = True
    try:
        await create_temporary_matcher(matcher, context)
        await ready
        activated = not pending or await context.wait_until_active()
    except BaseException:
        context.abort(ticket)
        raise
    if not activated or not context.active:
        context.abort(ticket)
        raise FinishedException

    state.clear()
    state.update(context.state)
    state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = ticket
    if is_shared_group_reply:
        state[QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY] = True
    if pending:
        request, request_token, feedback = _admit_semantic_request(
            context,
            event,
            is_shared_group_reply=is_shared_group_reply,
        )
        if feedback is not None:
            context.abort(ticket)
            await create_temporary_matcher(matcher, context)
            state[QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY] = True
            await _send_in_flight_feedback(matcher, event, feedback)
            raise FinishedException
    if request_token is not None:
        state[REQUEST_RESPONSE_TOKEN_STATE_KEY] = request_token
    context.mark_dispatched(ticket)
    action_id = request.action.id if request is not None else "none"
    logger.info(
        "queued conversation input dispatched: namespace=%s session=%s "
        "user=%s message_id=%s ticket=%s action=%s waited=%s queue_wait=%.3fs",
        context.namespace,
        context.event_session_id,
        event.user_id,
        event.message_id,
        ticket,
        action_id,
        waited,
        monotonic() - queued_at,
    )


def _admit_semantic_request(
    context: _QueuedConversation,
    event: MessageEvent,
    *,
    is_shared_group_reply: bool,
) -> tuple[SemanticRequest | None, object | None, str | None]:
    if context.semantic_request_resolver is None:
        return None, None, None
    if is_shared_group_reply:
        context.state[QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY] = True
    try:
        request = context.semantic_request_resolver(event, context.state)
    finally:
        context.state.pop(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY, None)
    coordinator = context.request_coordinator
    if request is None or coordinator is None:
        return request, None, None
    decision = coordinator.admit(
        user_id=event.user_id,
        request=request,
        scope=event_request_scope(event),
    )
    if decision.allowed:
        return request, decision.token, None
    return request, None, decision.feedback


async def _send_in_flight_feedback(
    matcher: Matcher,
    event: MessageEvent,
    feedback: str,
) -> None:
    if getattr(event, "group_id", None) is not None:
        await matcher.send(
            OneBotMessageSegment.at(event.user_id)
            + OneBotMessageSegment.text(f" {feedback}")
        )
        return
    await matcher.send(feedback)
