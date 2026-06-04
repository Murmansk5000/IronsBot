from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent


def _event_self_id(event: GroupMessageEvent) -> str:
    return str(getattr(event, "self_id", "") or "")


def _segment_at_qq(segment: Any) -> str:
    data = getattr(segment, "data", {}) or {}
    return str(data.get("qq", "") or "")


def mentions_bot(event: GroupMessageEvent) -> bool:
    is_tome = getattr(event, "is_tome", None)
    if callable(is_tome) and is_tome():
        return True

    self_id = _event_self_id(event)
    if not self_id:
        return False

    get_message = getattr(event, "get_message", None)
    message = get_message() if callable(get_message) else getattr(event, "message", [])

    return any(
        getattr(segment, "type", "") == "at" and _segment_at_qq(segment) == self_id
        for segment in message
    )


def replies_to_bot(event: GroupMessageEvent) -> bool:
    self_id = _event_self_id(event)
    if not self_id:
        return False

    reply = getattr(event, "reply", None)
    if reply is None:
        return False

    sender = getattr(reply, "sender", None)
    if isinstance(sender, dict):
        sender_id = sender.get("user_id")
    else:
        sender_id = getattr(sender, "user_id", None)

    return str(sender_id or "") == self_id


def mentions_or_replies_to_bot(event: GroupMessageEvent) -> bool:
    return mentions_bot(event) or replies_to_bot(event)
