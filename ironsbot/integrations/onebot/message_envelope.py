# SPDX-License-Identifier: MIT
"""Validate received OneBot message metadata without framework event models."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from ironsbot.integrations.onebot.message_segments import (
    OneBotMessage,
    OneBotMessageDecodeError,
    decode_onebot_segments,
)
from ironsbot.integrations.onebot.wire_fields import (
    OneBotInteger,  # noqa: TC001 - Pydantic field resolution
)

logger = logging.getLogger(__name__)


class OneBotSender(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: OneBotInteger | None = None
    nickname: str | None = None
    sex: str | None = None
    age: OneBotInteger | None = None
    card: str | None = None
    area: str | None = None
    level: str | None = None
    role: str | None = None
    title: str | None = None


class OneBotReplyEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: OneBotInteger
    message_type: str
    message_id: OneBotInteger
    real_id: OneBotInteger
    sender: OneBotSender
    message: OneBotMessage

    @field_validator("message", mode="before")
    @classmethod
    def decode_message(cls, value: object) -> OneBotMessage:
        return decode_onebot_segments(value)


class _Anonymous(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: OneBotInteger
    name: str
    flag: str


class _MessageFields(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: OneBotInteger
    self_id: OneBotInteger
    message_type: Literal["group", "private"]
    user_id: OneBotInteger
    message_id: OneBotInteger
    message: OneBotMessage
    group_id: OneBotInteger | None = None
    anonymous: _Anonymous | None = None
    to_me: bool = False
    reply: OneBotReplyEnvelope | None = None

    @model_validator(mode="after")
    def require_group_identity(self) -> Self:
        if self.message_type == "group" and self.group_id is None:
            message = "OneBot group message requires group_id"
            raise ValueError(message)
        return self


class OneBotMessageEnvelope(_MessageFields):
    post_type: Literal["message"]
    sub_type: str
    raw_message: str
    font: OneBotInteger
    sender: OneBotSender


class OneBotSentMessageEnvelope(_MessageFields):
    post_type: Literal["message_sent"]
    sub_type: str | None = None
    raw_message: str = ""
    font: OneBotInteger | None = None
    sender: OneBotSender | None = None


def decode_received_message(
    payload: dict[str, Any],
) -> OneBotMessageEnvelope | OneBotSentMessageEnvelope | None:
    try:
        canonical = {
            **payload,
            "message": decode_onebot_segments(payload.get("message")),
        }
        if "original_message" in payload:
            canonical["original_message"] = decode_onebot_segments(
                payload["original_message"]
            )
    except OneBotMessageDecodeError:
        logger.warning("OneBot message rejected: invalid message segments")
        return None
    try:
        model = (
            OneBotSentMessageEnvelope
            if payload.get("post_type") == "message_sent"
            else OneBotMessageEnvelope
        )
        return model.model_validate(canonical)
    except ValidationError:
        logger.warning("OneBot message rejected: invalid message envelope")
        return None
