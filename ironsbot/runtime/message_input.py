# SPDX-License-Identifier: MIT
"""Normalized OneBot message input used by command routing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import IncomingMessageRef
from ironsbot.runtime.onebot_identity import onebot_actor_ref, onebot_conversation_ref

if TYPE_CHECKING:
    from nonebot.adapters import Event

_RAW_AT_PATTERN = re.compile(r"\[(?:CQ:)?at,qq=([^\],]+)")


class OneBotMessageInputError(ValueError):
    @classmethod
    def missing_user_id(cls) -> OneBotMessageInputError:
        return cls("OneBot message event has no user_id")

    @classmethod
    def missing_message_id(cls) -> OneBotMessageInputError:
        return cls("OneBot message event has no message_id")

    @classmethod
    def missing_reply_message_id(cls) -> OneBotMessageInputError:
        return cls("OneBot reply metadata has no message_id")


def message_input_context(event: Event) -> MessageInputContext:
    """Read direct message segments once for every routing decision.

    ``event.reply`` is metadata for a different message. Its text and ``@``
    segments deliberately never participate here.
    """

    self_id = str(getattr(event, "self_id", "") or "").strip()
    message = _current_message(event)
    mentions_bot = False
    member_ids: list[str] = []

    for segment in message:
        if getattr(segment, "type", "") != "at":
            continue
        raw_target = str(getattr(segment, "data", {}).get("qq", "")).strip()
        if self_id and raw_target == self_id:
            mentions_bot = True
            continue
        if raw_target.isdigit() and raw_target not in member_ids:
            member_ids.append(raw_target)

    raw_message = str(getattr(event, "raw_message", "") or "")
    raw_targets = tuple(
        match.group(1).strip() for match in _RAW_AT_PATTERN.finditer(raw_message)
    )
    if raw_targets and self_id and self_id in raw_targets:
        mentions_bot = True
    # OneBot adapters may remove a group @ segment before matcher rules run and
    # leave only ``to_me``. Private messages can also be marked ``to_me`` by
    # transports, but are ordinary direct input rather than a bot mention.
    to_me = getattr(event, "is_tome", False)
    if isinstance(event, GroupMessageEvent) and bool(
        to_me() if callable(to_me) else to_me
    ):
        mentions_bot = True

    try:
        text = event.get_plaintext()
    except Exception:  # noqa: BLE001
        text = ""
    user_id = _event_user_id(event)
    actor = onebot_actor_ref(user_id)
    group_id = getattr(event, "group_id", None)
    conversation = onebot_conversation_ref(user_id, group_id=group_id)
    return MessageInputContext(
        IncomingMessageRef(
            id=_message_id(event),
            actor=actor,
            conversation=conversation,
            text=text,
            direct_mentions=tuple(
                onebot_actor_ref(member_id) for member_id in member_ids
            ),
            reply_to_id=_reply_message_id(event),
        ),
        mentions_bot=mentions_bot,
    )


def _current_message(event: Event) -> Any:
    """Prefer the original current message so bot preprocessing cannot hide @."""

    return getattr(event, "original_message", None) or getattr(event, "message", ())


def _message_id(event: Event) -> str:
    value = getattr(event, "message_id", None)
    if value is None:
        raise OneBotMessageInputError.missing_message_id()
    return str(value)


def _event_user_id(event: Event) -> str:
    value = getattr(event, "user_id", None)
    if value is None:
        raise OneBotMessageInputError.missing_user_id()
    return str(value)


def _reply_message_id(event: Event) -> str | None:
    reply = getattr(event, "reply", None)
    if reply is None:
        return None
    value = getattr(reply, "message_id", None)
    if value is None:
        raise OneBotMessageInputError.missing_reply_message_id()
    return str(value)
