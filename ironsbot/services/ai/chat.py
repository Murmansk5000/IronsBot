from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.services.ai.constants import EMPTY_REPLY, REQUEST_FAILED_REPLY
from ironsbot.services.ai.history import (
    HistoryMessage,
    append_turn,
    get_history,
    history_key,
)
from ironsbot.services.ai.memory import (
    append_user_memory,
    get_user_memory,
)
from ironsbot.shared.features import group_has_feature, is_superuser

if TYPE_CHECKING:
    from ironsbot.services.ai.resources import AiResources


@dataclass(frozen=True, slots=True)
class AiChatContext:
    key: str
    prompt: str
    history: list[HistoryMessage]
    memory: list[HistoryMessage]


def can_show_admin_notice(event: MessageEvent) -> bool:
    if is_superuser(event.user_id):
        return True

    if isinstance(event, GroupMessageEvent):
        return group_has_feature(event.group_id, "admin_notice")

    return False


def get_ai_chat_key(event: MessageEvent) -> str:
    return history_key(event)


def build_ai_chat_context(
    resources: AiResources,
    event: MessageEvent,
    prompt: str,
    *,
    key: str | None = None,
) -> AiChatContext:
    chat_key = key or get_ai_chat_key(event)
    history = get_history(resources, chat_key)
    memory = get_user_memory(
        resources.config,
        event,
        current_session_key=chat_key,
        has_short_history=bool(history),
    )
    return AiChatContext(
        key=chat_key,
        prompt=prompt,
        history=history,
        memory=memory,
    )


def is_ai_error_reply(reply: str) -> bool:
    return reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}


def record_successful_ai_reply(
    resources: AiResources,
    event: MessageEvent,
    context: AiChatContext,
    reply: str,
) -> None:
    append_turn(resources, context.key, context.prompt, reply)
    append_user_memory(
        resources.config,
        event,
        session_key=context.key,
        prompt=context.prompt,
        reply=reply,
    )
