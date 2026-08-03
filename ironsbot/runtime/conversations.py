# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nonebot.adapters import Event  # noqa: TC002 - dynamic callback annotation
from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.core.commands import command_text_matches
from ironsbot.runtime.matchers import (
    enter_prompt_loop,
    get_prompt_session_manager,
    get_queued_conversation,
)
from ironsbot.runtime.replies import build_message, event_sender_at_user_ids

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.runtime.matcher_contracts import QueuedSemanticRequestResolver

EventReplyCheck = Callable[[MessageEvent], bool]


def event_conversation_session_id(namespace: str, event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    target = f"group:{group_id}" if group_id is not None else "private"
    return f"{namespace}:{target}:user:{event.user_id}"


def is_self_message_event(event: MessageEvent) -> bool:
    return event.user_id == event.self_id


def command_reply_check(commands: tuple[str, ...] | list[str]) -> EventReplyCheck:
    def _check(event: MessageEvent) -> bool:
        return command_text_matches(event.get_plaintext(), commands)

    return _check


async def enter_event_reply_conversation(  # noqa: PLR0913
    matcher: Any,
    event: MessageEvent,
    *,
    namespace: str,
    handlers: list[Callable[..., object]],
    reply_check: EventReplyCheck,
    prompt: str | Message | None = None,
    queue_semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
    group_reply_check: EventReplyCheck | None = None,
    allow_group_reply_exit: bool = False,
) -> None:
    queued = get_queued_conversation(matcher)
    if queued is not None and queued.namespace == namespace:
        session_id = queued.conversation_session_id
        owner_event_session_id = queued.event_session_id
    else:
        session_id = event_conversation_session_id(namespace, event)
        owner_event_session_id = event.get_session_id()
    if not isinstance(session_id, str):
        session_id = event_conversation_session_id(namespace, event)
    prompt_sessions = get_prompt_session_manager(matcher)
    version = prompt_sessions.acquire(session_id)

    def _is_same_conversation_reply(next_event: Event) -> bool:
        if not isinstance(next_event, MessageEvent):
            return False

        if next_event.get_session_id() != owner_event_session_id:
            return False

        if is_self_message_event(next_event):
            return False

        if getattr(next_event, "reply", None) is not None:
            return False

        return reply_check(next_event)

    prompt_message = (
        None
        if prompt is None
        else build_message(
            prompt,
            at_user_ids=event_sender_at_user_ids(event),
        )
    )
    rule = prompt_sessions.make_rule(
        session_id,
        version,
        _is_same_conversation_reply,
    )

    def _is_group_menu_reply(next_event: Event) -> bool:
        if not isinstance(next_event, MessageEvent):
            return False
        check = group_reply_check or reply_check
        return check(next_event)

    await enter_prompt_loop(
        matcher,
        handlers=handlers,
        rule=rule,
        prompt=prompt_message,
        queue_namespace=namespace,
        queue_reply_check=_is_same_conversation_reply,
        queue_group_reply_check=_is_group_menu_reply,
        queue_allow_group_reply_exit=allow_group_reply_exit,
        queue_semantic_request_resolver=queue_semantic_request_resolver,
        queue_event_session_id=owner_event_session_id,
        queue_conversation_session_id=session_id,
    )
