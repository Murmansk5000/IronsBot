# SPDX-License-Identifier: MIT
"""Translate Tencent SDK events into opaque core identity values."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    OfficialUnionIdentity,
    Platform,
)

if TYPE_CHECKING:
    from qqbot_agent_sdk.event_parser import InboundEvent

GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"
GROUP_MESSAGE_CREATE = "GROUP_MESSAGE_CREATE"
_LEADING_NAMED_MENTION_RE = re.compile(r"^[\s]*[@＠]\S+[\s]*")
_PASSIVE_REPLY_WINDOWS = {
    "group": timedelta(minutes=5),
    "private": timedelta(minutes=60),
}


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
        text=_message_text(event, raw),
        direct_mentions=direct_mentions,
        group_role=group_role,
        reply_to_id=_reply_reference(event, raw),
        reply_reference_ids=_reply_references(event, raw),
        sequence=_message_sequence(raw),
        reply_deadline=_reply_deadline(event, conversation.kind),
        official_union_identity=_official_union_identity(raw),
    )


def qq_official_event_mentions_bot(event: InboundEvent) -> bool:
    if event.event_type == GROUP_AT_MESSAGE_CREATE:
        return True
    if event.event_type != GROUP_MESSAGE_CREATE:
        return False
    raw = event.raw if isinstance(event.raw, Mapping) else {}
    return _bot_mention(raw) is not None


def qq_official_event_mentions_everyone(event: InboundEvent) -> bool:
    raw = event.raw if isinstance(event.raw, Mapping) else {}
    if raw.get("at_all") is True:
        return True
    mentions = raw.get("mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return False
    return any(
        isinstance(mention, Mapping)
        and (
            mention.get("at_all") is True or mention.get("type") in ("all", "everyone")
        )
        for mention in mentions
    )


def _message_text(event: InboundEvent, raw: Mapping[str, object]) -> str:
    text = event.content.strip()
    if event.event_type == GROUP_MESSAGE_CREATE:
        mention = _bot_mention(raw)
        if mention is not None:
            text = _remove_leading_self_mention(text, mention, raw)
    return _remove_direct_member_mention_markers(text, raw).strip()


def _remove_direct_member_mention_markers(
    text: str,
    raw: Mapping[str, object],
) -> str:
    """Remove only markers backed by structured member-mention metadata."""

    mentions = raw.get("mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return text
    for mention in mentions:
        if not isinstance(mention, Mapping):
            continue
        if bool(mention.get("is_you")) or bool(mention.get("bot")):
            continue
        markers: list[str] = []
        member_openid = str(mention.get("member_openid", "")).strip()
        if member_openid:
            markers.extend((f"<@{member_openid}>", f"<@!{member_openid}>"))
        username = str(mention.get("username", "")).strip()
        if username:
            markers.extend((f"@{username}", f"＠{username}"))
        positions = tuple(
            (position, marker)
            for marker in markers
            if (position := text.find(marker)) >= 0
        )
        if not positions:
            continue
        position, marker = min(positions, key=lambda item: item[0])
        text = f"{text[:position]} {text[position + len(marker) :]}"
    return text


def _bot_mention(raw: Mapping[str, object]) -> Mapping[str, object] | None:
    mentions = raw.get("mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return None
    for mention in mentions:
        if isinstance(mention, Mapping) and bool(mention.get("is_you")):
            return mention
    return None


def _remove_leading_self_mention(
    text: str,
    mention: Mapping[str, object],
    raw: Mapping[str, object],
) -> str:
    stripped = text.lstrip()
    member_openid = str(mention.get("member_openid", "")).strip()
    if member_openid:
        for marker in (f"<@{member_openid}>", f"<@!{member_openid}>"):
            if stripped.startswith(marker):
                return stripped.removeprefix(marker).lstrip()
    if _first_mention_is_self(raw):
        return _LEADING_NAMED_MENTION_RE.sub("", text, count=1)
    return text


def _first_mention_is_self(raw: Mapping[str, object]) -> bool:
    mentions = raw.get("mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return False
    return bool(
        mentions and isinstance(mentions[0], Mapping) and mentions[0].get("is_you")
    )


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
        member_openid = str(mention.get("member_openid", "")).strip()
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
    value = str(author.get(key, "")).strip()
    return value or None


def _official_union_identity(
    raw: Mapping[str, object],
) -> OfficialUnionIdentity | None:
    union_openid = _author_value(raw, "union_openid")
    union_user_account = _author_value(raw, "union_user_account")
    if union_openid is None and union_user_account is None:
        return None
    return OfficialUnionIdentity(union_openid, union_user_account)


def _reply_reference(
    event: InboundEvent,
    raw: Mapping[str, object],
) -> str | None:
    if event.message_type != MSG_TYPE_QUOTE:
        return None
    reference = raw.get("message_reference")
    if isinstance(reference, Mapping):
        message_id = reference.get("message_id")
        if isinstance(message_id, str) and message_id.strip():
            return message_id
    if reference := _scene_value(raw, "ref_msg_idx"):
        return reference
    elements = raw.get("msg_elements")
    if isinstance(elements, list) and elements and isinstance(elements[0], Mapping):
        reference = elements[0].get("msg_idx")
        if isinstance(reference, (str, int)) and str(reference).strip():
            return str(reference)
    return f"quoted:{event.message_id}"


def _reply_references(
    event: InboundEvent, raw: Mapping[str, object]
) -> tuple[str, ...]:
    primary = _reply_reference(event, raw)
    if primary is None:
        return ()
    values = [primary]
    if sequence := _scene_value(raw, "ref_msg_idx"):
        values.append(sequence)
    return tuple(dict.fromkeys(values))


def _message_sequence(raw: Mapping[str, object]) -> str | None:
    direct = str(raw.get("msg_idx", "")).strip()
    return direct or _scene_value(raw, "msg_idx")


def _reply_deadline(event: InboundEvent, conversation_kind: str) -> datetime | None:
    value = getattr(event, "timestamp", None)
    if isinstance(value, datetime):
        timestamp = value
    else:
        normalized = str(value or "").strip().replace("Z", "+00:00")
        if not normalized:
            return None
        try:
            timestamp = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        return None
    return timestamp + _PASSIVE_REPLY_WINDOWS[conversation_kind]


def _scene_value(raw: Mapping[str, object], key: str) -> str | None:
    scene = raw.get("message_scene")
    if not isinstance(scene, Mapping):
        return None
    ext = scene.get("ext")
    if not isinstance(ext, Sequence) or isinstance(ext, (str, bytes)):
        return None
    prefix = f"{key}="
    for item in ext:
        value = str(item)
        if value.startswith(prefix):
            normalized = value.removeprefix(prefix).strip()
            return normalized or None
    return None
