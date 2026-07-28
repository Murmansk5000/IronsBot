# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.core.commands import command_text_matches
from ironsbot.runtime.matchers import (
    enter_prompt_loop,
    get_prompt_session_manager,
)
from ironsbot.runtime.replies import build_message, event_sender_at_user_ids

if TYPE_CHECKING:
    from nonebot.adapters import Event
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
) -> None:
    session_id = event_conversation_session_id(namespace, event)
    prompt_sessions = get_prompt_session_manager(matcher)
    version = prompt_sessions.acquire(session_id)

    def _is_same_conversation_reply(next_event: Event) -> bool:
        if not isinstance(next_event, MessageEvent):
            return False

        if event_conversation_session_id(namespace, next_event) != session_id:
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
    await enter_prompt_loop(
        matcher,
        handlers=handlers,
        rule=rule,
        prompt=prompt_message,
        queue_namespace=namespace,
        queue_reply_check=_is_same_conversation_reply,
        queue_semantic_request_resolver=queue_semantic_request_resolver,
    )
