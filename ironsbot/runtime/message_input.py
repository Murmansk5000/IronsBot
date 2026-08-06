# SPDX-License-Identifier: MIT
"""Normalized OneBot message input used by command routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.runtime.onebot_reply import event_reply_message_id

if TYPE_CHECKING:
    from nonebot.adapters import Event

_RAW_AT_PATTERN = re.compile(r"\[(?:CQ:)?at,qq=([^\],]+)")


class MessageInputKind(str, Enum):
    """Single routing class, evaluated in the declared precedence order."""

    REPLY = "reply"
    BOT_MENTION = "bot_mention"
    MEMBER_MENTION = "member_mention"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class MessageInputContext:
    """Only the newly-sent message, never the quoted message body."""

    text: str
    is_reply: bool
    has_any_mention: bool
    mentions_bot: bool
    member_user_ids: tuple[int, ...]

    @property
    def kind(self) -> MessageInputKind:
        if self.is_reply:
            return MessageInputKind.REPLY
        if self.mentions_bot:
            return MessageInputKind.BOT_MENTION
        if self.has_any_mention:
            return MessageInputKind.MEMBER_MENTION
        return MessageInputKind.DIRECT

    @property
    def has_member_mentions(self) -> bool:
        return bool(self.member_user_ids) or (
            self.has_any_mention and not self.mentions_bot
        )


def message_input_context(event: Event) -> MessageInputContext:
    """Read direct message segments once for every routing decision.

    ``event.reply`` is metadata for a different message. Its text and ``@``
    segments deliberately never participate here.
    """

    self_id = str(getattr(event, "self_id", "") or "").strip()
    message = _current_message(event)
    has_any_mention = False
    mentions_bot = False
    member_ids: list[int] = []

    for segment in message:
        if getattr(segment, "type", "") != "at":
            continue
        has_any_mention = True
        raw_target = str(getattr(segment, "data", {}).get("qq", "")).strip()
        if self_id and raw_target == self_id:
            mentions_bot = True
            continue
        if raw_target.isdigit():
            member_id = int(raw_target)
            if member_id not in member_ids:
                member_ids.append(member_id)

    raw_message = str(getattr(event, "raw_message", "") or "")
    raw_targets = tuple(
        match.group(1).strip() for match in _RAW_AT_PATTERN.finditer(raw_message)
    )
    if raw_targets:
        has_any_mention = True
        if self_id and self_id in raw_targets:
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
    return MessageInputContext(
        text=text,
        is_reply=event_reply_message_id(event) is not None,
        has_any_mention=has_any_mention,
        mentions_bot=mentions_bot,
        member_user_ids=tuple(member_ids),
    )


def _current_message(event: Event) -> Any:
    """Prefer the original current message so bot preprocessing cannot hide @."""

    return getattr(event, "original_message", None) or getattr(event, "message", ())
