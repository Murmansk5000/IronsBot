# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.shared.config.config import (
    GroupCommandMessageAction,
    GroupScheduledMessageAction,
    MeetingConfig,
    PicConfig,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    ReplyLineConfig,
)
from ironsbot.shared.config.parsing import string_list


class SendpicBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnb_repo: str | None = None
    local_root: Path = Path("sendpic")
    configs: list[PicConfig] = Field(default_factory=list)
    enabled_ids: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("enabled_ids", mode="before")
    @classmethod
    def normalize_enabled_ids(cls, value: object) -> object:
        return string_list(value)


class MessageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: ReplyLineConfig = Field(default_factory=ReplyLineConfig)
    private_commands: list[PrivateCommandMessageAction] = Field(default_factory=list)
    private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    group_commands: list[GroupCommandMessageAction] = Field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = Field(default_factory=list)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    sendpic: SendpicBehaviorConfig = Field(default_factory=SendpicBehaviorConfig)


__all__ = ["MessageConfig", "SendpicBehaviorConfig"]
