# SPDX-License-Identifier: MIT
"""OneBot ingress gate for interactive and silent-verifier deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
)
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from ironsbot.services.identity_observation import OneBotGroupMessageObservation

if TYPE_CHECKING:
    from ironsbot.services.identity_observation import (
        SilentIdentityObservationService,
    )

_SILENT_REASON = "OneBot is running in silent verifier mode"


@dataclass(frozen=True, slots=True)
class OneBotIngressPolicy:
    messages_enabled: bool
    identity_observer: SilentIdentityObservationService | None = None

    async def process(self, event: Event) -> None:
        observation = _group_message_observation(event)
        if self.identity_observer is not None and observation is not None:
            await self.identity_observer.observe_onebot(observation)
        if not self.messages_enabled:
            raise IgnoredException(_SILENT_REASON)

    def install(self) -> None:
        policy = self

        @event_preprocessor
        async def enforce_onebot_ingress(event: Event) -> None:
            await policy.process(event)


def _group_message_observation(
    event: Event,
) -> OneBotGroupMessageObservation | None:
    if isinstance(event, GroupMessageEvent):
        message = event.original_message or event.message
        sender_id = event.user_id
        group_id = event.group_id
        message_id = event.message_id
        reply_sender_id = (
            event.reply.sender.user_id if event.reply is not None else None
        )
    elif (
        event.post_type == "message_sent"
        and getattr(event, "message_type", None) == "group"
    ):
        message = _message_sent_content(event)
        sender_id = _integer_field(event, "user_id")
        group_id = _integer_field(event, "group_id")
        message_id = _integer_field(event, "message_id")
        reply_sender_id = None
        if (
            message is None
            or sender_id is None
            or group_id is None
            or message_id is None
        ):
            return None
    else:
        return None
    return OneBotGroupMessageObservation(
        sender_id=sender_id,
        self_id=event.self_id,
        group_id=group_id,
        mentioned_qq_ids=_mentioned_qq_ids(message, reply_sender_id=reply_sender_id),
        text=message.extract_plain_text(),
        message_id=str(message_id),
    )


def _message_sent_content(event: Event) -> Message | None:
    raw = getattr(event, "message", None)
    if isinstance(raw, Message):
        return raw
    if not isinstance(raw, list):
        return None
    segments: list[MessageSegment] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        segment_type = item.get("type")
        data = item.get("data")
        if not isinstance(segment_type, str) or not isinstance(data, dict):
            return None
        segments.append(MessageSegment(segment_type, data))
    return Message(segments)


def _integer_field(event: Event, name: str) -> int | None:
    value = getattr(event, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _mentioned_qq_ids(
    message: Message,
    *,
    reply_sender_id: int | None,
) -> tuple[str, ...]:
    values: list[str] = []
    for segment in message:
        if segment.type != "at":
            continue
        value = str(segment.data.get("qq", "")).strip()
        if value.isdecimal() and value not in values:
            values.append(value)
    if not values and reply_sender_id is not None:
        value = str(reply_sender_id).strip()
        if value.isdecimal():
            values.append(value)
    return tuple(values)
