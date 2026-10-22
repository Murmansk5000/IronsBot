# SPDX-License-Identifier: MIT
"""Decode OneBot message facts without framework events or preprocessing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import IncomingMessageRef, Platform
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.message_segments import OneBotSegment

_RAW_AT_PATTERN = re.compile(r"\[(?:CQ:)?at,qq=([^\],]+)")


@dataclass(frozen=True, slots=True)
class OneBotMessageFacts:
    account_id: str
    user_id: str
    message_id: str
    text: str
    segments: tuple[OneBotSegment, ...] = ()
    original_segments: tuple[OneBotSegment, ...] | None = None
    group_id: str | None = None
    group_role: str | None = None
    reply_to_id: str | None = None
    reply_sender_id: str | None = None
    raw_message: str = ""
    addressed_to_bot: bool = False
    actor_display_name: str = ""


def decode_onebot_message(facts: OneBotMessageFacts) -> MessageInputContext:
    segments = facts.original_segments or facts.segments
    mentions_bot = facts.addressed_to_bot
    member_ids: list[str] = []
    for segment in segments:
        if segment["type"] != "at":
            continue
        target = str(segment["data"].get("qq", "")).strip()
        if facts.account_id and target == facts.account_id:
            mentions_bot = True
        elif target.isdigit() and target not in member_ids:
            member_ids.append(target)
    raw_targets = tuple(
        match.group(1).strip() for match in _RAW_AT_PATTERN.finditer(facts.raw_message)
    )
    mentions_bot = mentions_bot or bool(
        facts.account_id and facts.account_id in raw_targets
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=onebot_actor_ref(facts.user_id),
            conversation=onebot_conversation_ref(
                facts.user_id, group_id=facts.group_id
            ),
            message_id=facts.message_id,
            text=facts.text,
            direct_mentions=tuple(onebot_actor_ref(value) for value in member_ids),
            reply_to_id=_reply_id(facts),
            group_role=facts.group_role if facts.group_id is not None else None,
        ),
        mentions_bot=mentions_bot,
        mentions_everyone="all" in raw_targets
        or any(
            segment["type"] == "at" and str(segment["data"].get("qq", "")) == "all"
            for segment in segments
        ),
        execution_identity=(
            ExecutionIdentity(Platform.ONEBOT, facts.account_id)
            if facts.account_id
            else None
        ),
        actor_display_name=facts.actor_display_name.strip(),
    )


def _reply_id(facts: OneBotMessageFacts) -> str | None:
    if facts.reply_to_id is not None:
        return facts.reply_to_id
    for message in (facts.segments, facts.original_segments or ()):
        for segment in message:
            if segment["type"] == "reply" and segment["data"].get("id") is not None:
                return str(segment["data"]["id"])
    return None
