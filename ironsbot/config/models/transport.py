# SPDX-License-Identifier: MIT
"""Transport-specific configuration models."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OneBotConfig(BaseModel):
    """OneBot ingress and fallback outbound policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    send_messages: bool = True
    identity_verification: bool = False
    trusted_official_bots: dict[str, int] = Field(default_factory=dict)

    @field_validator("trusted_official_bots", mode="before")
    @classmethod
    def normalize_trusted_official_bots(cls, value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            msg = "bot.onebot.trusted_official_bots must be a table"
            raise TypeError(msg)
        result: dict[str, int] = {}
        for raw_alias, raw_id in value.items():
            alias = str(raw_alias).strip()
            try:
                bot_id = int(raw_id)
            except (TypeError, ValueError) as error:
                msg = f"bot.onebot.trusted_official_bots.{alias} must be a QQ number"
                raise ValueError(msg) from error
            if not alias or bot_id <= 0:
                msg = "trusted official bot aliases and QQ numbers must be positive"
                raise ValueError(msg)
            result[alias] = bot_id
        if len(set(result.values())) != len(result):
            msg = "trusted official bot QQ numbers must be unique"
            raise ValueError(msg)
        return result
