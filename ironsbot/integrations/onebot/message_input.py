# SPDX-License-Identifier: MIT
"""Normalized OneBot message input used by command routing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import IncomingMessageRef, Platform
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.platform import ActorRef

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
    mentions_bot, member_mentions = _direct_mentions(event, self_id=self_id)

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
            platform=Platform.ONEBOT,
            actor=actor,
            conversation=conversation,
            message_id=_message_id(event),
            text=text,
            direct_mentions=member_mentions,
            reply_to_id=event_reply_message_id(event),
        ),
        mentions_bot=mentions_bot,
        execution_identity=(
            ExecutionIdentity(Platform.ONEBOT, self_id) if self_id else None
        ),
    )


def onebot_direct_member_mentions(event: Event) -> tuple[ActorRef, ...]:
    """Read current-message member targets without requiring event metadata."""

    self_id = str(getattr(event, "self_id", "") or "").strip()
    return _direct_mentions(event, self_id=self_id)[1]


def _direct_mentions(
    event: Event,
    *,
    self_id: str,
) -> tuple[bool, tuple[ActorRef, ...]]:
    mentions_bot = False
    member_ids: list[str] = []
    for segment in _current_message(event):
        if getattr(segment, "type", "") != "at":
            continue
        raw_target = str(getattr(segment, "data", {}).get("qq", "")).strip()
        if self_id and raw_target == self_id:
            mentions_bot = True
            continue
        if raw_target.isdigit() and raw_target not in member_ids:
            member_ids.append(raw_target)
    return mentions_bot, tuple(onebot_actor_ref(value) for value in member_ids)


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


def event_reply_message_id(event: Event) -> str | None:
    """Return the reply target from metadata or direct OneBot segments.

    Some OneBot transports retain a reply segment in the current message while
    omitting ``event.reply`` metadata. Both representations describe the same
    incoming event, so routing must accept either one.
    """
    reply = getattr(event, "reply", None)
    if reply is not None:
        value = getattr(reply, "message_id", None)
        if value is None:
            raise OneBotMessageInputError.missing_reply_message_id()
        return str(value)
    for message in _message_candidates(event):
        for segment in message:
            if getattr(segment, "type", "") != "reply":
                continue
            value = getattr(segment, "data", {}).get("id")
            if value is not None:
                return str(value)
    return None


def _message_candidates(event: Event) -> tuple[Any, ...]:
    current = getattr(event, "message", None)
    original = getattr(event, "original_message", None)
    return tuple(message for message in (current, original) if message is not None)
