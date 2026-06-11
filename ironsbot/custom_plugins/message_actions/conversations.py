from typing import Any

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher

from ironsbot.shared.messaging.conversations import (
    EventReplyCheck,
    command_reply_check,
    event_conversation_session_id,
)
from ironsbot.shared.messaging.replies import event_sender_at_user_ids
from ironsbot.utils.matcher import enter_prompt_loop, prompt_session_manager

from .reply_limits import limit_message_by_reply_lines
from .text import build_message

__all__ = [
    "EventReplyCheck",
    "command_reply_check",
    "enter_event_reply_conversation",
    "event_conversation_session_id",
]


async def enter_event_reply_conversation(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    *,
    namespace: str,
    handlers: list[Any],
    reply_check: EventReplyCheck,
    prompt: str | Message | None = None,
    mention_sender: bool = False,
) -> None:
    session_id = event_conversation_session_id(namespace, event)
    version = prompt_session_manager.acquire(session_id)

    def _is_same_conversation_reply(next_event: Event) -> bool:
        if not isinstance(next_event, MessageEvent):
            return False

        if event_conversation_session_id(namespace, next_event) != session_id:
            return False

        return reply_check(next_event)

    prompt_message = (
        None
        if prompt is None
        else build_message(
            limit_message_by_reply_lines(prompt, event=event),
            at_user_ids=event_sender_at_user_ids(
                event,
                mention_sender=mention_sender,
            ),
        )
    )
    rule = prompt_session_manager.make_rule(
        session_id,
        version,
        _is_same_conversation_reply,
    )
    await enter_prompt_loop(
        matcher,
        handlers=handlers,
        rule=rule,
        prompt=prompt_message,
    )
