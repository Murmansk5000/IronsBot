# SPDX-License-Identifier: MIT
"""Transport-specific configuration models."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import (
    AnyHttpUrl,
    AnyWebsocketUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing_extensions import Self

BotReference = str | int


class OneBotRoutingConfig(BaseModel):
    """Account ownership for OneBot ingress and proactive delivery."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_bot: BotReference | None = None
    bot_aliases: dict[str, int] = Field(default_factory=dict)
    groups: dict[str, BotReference] = Field(default_factory=dict)
    users: dict[str, BotReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        invalid_aliases = [
            alias
            for alias, bot_id in self.bot_aliases.items()
            if not alias.strip() or bot_id <= 0
        ]
        if invalid_aliases:
            msg = "bot.onebot.routing.bot_aliases contains invalid entries"
            raise ValueError(msg)

        invalid_targets = [
            f"bot.onebot.routing.{mapping_name}.{target}"
            for mapping_name, mapping in (
                ("groups", self.groups),
                ("users", self.users),
            )
            for target, bot_ref in mapping.items()
            if not target.strip() or self.resolve_bot_reference(bot_ref) is None
        ]
        if (
            self.default_bot is not None
            and self.resolve_bot_reference(self.default_bot) is None
        ):
            invalid_targets.append("bot.onebot.routing.default_bot")
        if invalid_targets:
            msg = "unknown or invalid bot reference(s): " + ", ".join(invalid_targets)
            raise ValueError(msg)
        return self

    def resolve_bot_reference(self, reference: BotReference) -> int | None:
        if isinstance(reference, int):
            return reference if reference > 0 else None
        normalized = reference.strip()
        if normalized in self.bot_aliases:
            return self.bot_aliases[normalized]
        if normalized.isdigit() and int(normalized) > 0:
            return int(normalized)
        return None


class SelfCommandsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    prefixes: list[str] = Field(default_factory=lambda: ["演示 ", "示范 "])

    @field_validator("prefixes")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        if not value or any(not prefix.strip() for prefix in value):
            msg = "self command prefixes must contain non-whitespace text"
            raise ValueError(msg)
        return sorted(set(value), key=len, reverse=True)


class OneBotConfig(BaseModel):
    """OneBot ingress, identity observation and outbound policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    send_messages: bool = True
    identity_verification: bool = False
    api_timeout: float | None = Field(default=30.0, gt=0, allow_inf_nan=False)
    ws_urls: set[AnyWebsocketUrl] = Field(default_factory=set)
    api_roots: dict[str, AnyHttpUrl] = Field(default_factory=dict)
    nicknames: set[str] = Field(default_factory=set)
    http_secret: str = Field(default="", exclude=True, repr=False)
    routing: OneBotRoutingConfig = Field(default_factory=OneBotRoutingConfig)
    self_commands: SelfCommandsConfig = Field(default_factory=SelfCommandsConfig)
    trusted_official_bots: dict[str, int] = Field(default_factory=dict)

    @field_validator("nicknames")
    @classmethod
    def validate_nicknames(cls, value: set[str]) -> set[str]:
        if any(not name.strip() for name in value):
            msg = "bot.onebot.nicknames must contain non-whitespace names"
            raise ValueError(msg)
        return value

    @field_validator("api_roots")
    @classmethod
    def validate_api_accounts(
        cls, value: dict[str, AnyHttpUrl]
    ) -> dict[str, AnyHttpUrl]:
        if any(
            not account.isascii() or not account.isdecimal() or int(account) <= 0
            for account in value
        ):
            msg = "bot.onebot.api_roots keys must be positive numeric OneBot accounts"
            raise ValueError(msg)
        return value

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
