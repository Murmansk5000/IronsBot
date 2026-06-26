from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_CQ_AT_PATTERN = re.compile(r"\[CQ:at,qq=([^\]]+)\]")
_LOG_AT_PATTERN = re.compile(r"\[at:qq=([^\],\]]+)")


def _event_self_id(event: GroupMessageEvent) -> str:
    return str(getattr(event, "self_id", "") or "")


def _segment_at_qq(segment: Any) -> str:
    data = getattr(segment, "data", {}) or {}
    return str(data.get("qq", "") or "")


def _iter_message_segments(message: Any) -> tuple[Any, ...]:
    if message is None:
        return ()
    if isinstance(message, str):
        return ()
    try:
        return tuple(message)
    except TypeError:
        return ()


def _message_has_bot_at(message: Any, self_id: str) -> bool:
    return any(
        getattr(segment, "type", "") == "at" and _segment_at_qq(segment) == self_id
        for segment in _iter_message_segments(message)
    )


def _text_has_bot_at(text: str, self_id: str) -> bool:
    if not text:
        return False

    for pattern in (_CQ_AT_PATTERN, _LOG_AT_PATTERN):
        if any(match.group(1).strip() == self_id for match in pattern.finditer(text)):
            return True
    return False


def _event_message(event: GroupMessageEvent) -> Any:
    get_message = getattr(event, "get_message", None)
    if callable(get_message):
        return get_message()
    return getattr(event, "message", [])


def _event_is_to_me(event: GroupMessageEvent) -> bool:
    is_tome = getattr(event, "is_tome", None)
    if callable(is_tome):
        return bool(is_tome())
    return bool(getattr(event, "to_me", False))


def _has_reply(event: GroupMessageEvent) -> bool:
    return getattr(event, "reply", None) is not None


def _has_explicit_bot_at(event: GroupMessageEvent, self_id: str) -> bool:
    if _message_has_bot_at(_event_message(event), self_id):
        return True

    original_message = getattr(event, "original_message", None)
    if _message_has_bot_at(original_message, self_id):
        return True

    raw_message = str(getattr(event, "raw_message", "") or "")
    return _text_has_bot_at(raw_message, self_id)


def mentions_bot(event: GroupMessageEvent) -> bool:
    self_id = _event_self_id(event)
    if not self_id:
        return False

    if _has_explicit_bot_at(event, self_id):
        return True

    # OneBot v11 preprocessing may strip a leading @bot segment and only leave
    # the to_me flag. Treat that as a mention unless it was only a reply.
    return _event_is_to_me(event) and not _has_reply(event)
