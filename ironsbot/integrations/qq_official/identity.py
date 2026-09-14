# SPDX-License-Identifier: MIT
"""Translate Tencent SDK events into opaque core identity values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)

if TYPE_CHECKING:
    from qqbot_agent_sdk.event_parser import InboundEvent

GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"


def qq_official_incoming_message(
    event: InboundEvent,
    *,
    account_id: str,
) -> IncomingMessageRef:
    raw = event.raw if isinstance(event.raw, Mapping) else {}
    if event.chat_scope == "group":
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            event.chat_id,
            account_id=account_id,
        )
        actor = ActorRef(
            Platform.QQ_OFFICIAL,
            event.user_id,
            "member",
            event.chat_id,
            account_id=account_id,
        )
        group_role = _author_value(raw, "member_role")
        direct_mentions = _direct_mentions(
            raw,
            conversation_id=event.chat_id,
            account_id=account_id,
        )
    elif event.chat_scope == "c2c":
        actor = ActorRef(
            Platform.QQ_OFFICIAL,
            event.user_id,
            account_id=account_id,
        )
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            event.chat_id,
            account_id=account_id,
        )
        group_role = None
        direct_mentions = ()
    else:
        msg = f"unsupported QQ Official message scope: {event.chat_scope}"
        raise TypeError(msg)
    return IncomingMessageRef(
        platform=Platform.QQ_OFFICIAL,
        actor=actor,
        conversation=conversation,
        message_id=event.message_id,
        text=event.content.strip(),
        direct_mentions=direct_mentions,
        group_role=group_role,
        reply_to_id=_reply_reference(event, raw),
        sequence=_message_sequence(raw),
    )


def is_qq_official_reply_event(event: InboundEvent) -> bool:
    raw = event.raw if isinstance(event.raw, Mapping) else {}
    return _reply_reference(event, raw) is not None


def qq_official_event_mentions_bot(event: InboundEvent) -> bool:
    return event.event_type == GROUP_AT_MESSAGE_CREATE


def _direct_mentions(
    raw: Mapping[str, object],
    *,
    conversation_id: str,
    account_id: str,
) -> tuple[ActorRef, ...]:
    mentions = raw.get("mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return ()
    result: list[ActorRef] = []
    for mention in mentions:
        if not isinstance(mention, Mapping):
            continue
        if bool(mention.get("is_you")) or bool(mention.get("bot")):
            continue
        member_openid = _string_value(mention.get("member_openid"))
        if not member_openid:
            continue
        result.append(
            ActorRef(
                Platform.QQ_OFFICIAL,
                member_openid,
                "member",
                conversation_id,
                account_id=account_id,
            )
        )
    return tuple(result)


def _author_value(raw: Mapping[str, object], key: str) -> str | None:
    author = raw.get("author")
    if not isinstance(author, Mapping):
        return None
    return _string_value(author.get(key))


def _reply_reference(
    event: InboundEvent,
    raw: Mapping[str, object],
) -> str | None:
    if event.message_type != MSG_TYPE_QUOTE:
        return None
    return _scene_value(raw, "ref_msg_idx") or f"quoted:{event.message_id}"


def _message_sequence(raw: Mapping[str, object]) -> str | None:
    direct = _string_value(raw.get("msg_idx"))
    return direct or _scene_value(raw, "msg_idx")


def _scene_value(raw: Mapping[str, object], key: str) -> str | None:
    scene = raw.get("message_scene")
    if not isinstance(scene, Mapping):
        return None
    ext = scene.get("ext")
    if not isinstance(ext, Sequence) or isinstance(ext, (str, bytes)):
        return None
    prefix = f"{key}="
    for item in ext:
        value = _string_value(item)
        if value is not None and value.startswith(prefix):
            normalized = value.removeprefix(prefix).strip()
            return normalized or None
    return None


def _string_value(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None
