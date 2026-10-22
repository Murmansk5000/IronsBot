# SPDX-License-Identifier: MIT
"""Validate received OneBot message metadata without framework event models."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from ironsbot.integrations.onebot.message_segments import (
    OneBotMessage,
    decode_onebot_segments,
)


def _integer(value: Any) -> Any:
    if isinstance(value, bool):
        message = "OneBot integer field cannot be boolean"
        raise PydanticCustomError("onebot_integer", message)
    return value


_WireInteger = Annotated[int, BeforeValidator(_integer)]


class OneBotSender(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: _WireInteger | None = None
    nickname: str | None = None
    sex: str | None = None
    age: _WireInteger | None = None
    card: str | None = None
    area: str | None = None
    level: str | None = None
    role: str | None = None
    title: str | None = None


class OneBotReplyEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: _WireInteger
    message_type: str
    message_id: _WireInteger
    real_id: _WireInteger
    sender: OneBotSender
    message: OneBotMessage

    @field_validator("message", mode="before")
    @classmethod
    def decode_message(cls, value: object) -> OneBotMessage:
        return decode_onebot_segments(value)


class _Anonymous(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: _WireInteger
    name: str
    flag: str


class OneBotMessageEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: _WireInteger
    self_id: _WireInteger
    post_type: Literal["message"]
    message_type: Literal["group", "private"]
    sub_type: str
    user_id: _WireInteger
    message_id: _WireInteger
    message: OneBotMessage
    raw_message: str
    font: _WireInteger
    sender: OneBotSender
    group_id: _WireInteger | None = None
    anonymous: _Anonymous | None = None
    to_me: bool = False
    reply: OneBotReplyEnvelope | None = None

    @model_validator(mode="after")
    def require_group_identity(self) -> OneBotMessageEnvelope:
        if self.message_type == "group" and self.group_id is None:
            message = "OneBot group message requires group_id"
            raise ValueError(message)
        return self
