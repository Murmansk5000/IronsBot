# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.config.models.operations import OperationsConfig
from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.commands import NormalizedIntList, csv_items, json_array
from ironsbot.core.features import FeatureConfig

VALID_LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def _command_starts(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_items: Iterable[object] = (
            json_array(text, name="command start")
            if text.startswith("[")
            else csv_items(text)
        )
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        return []

    result: list[str] = []
    for raw_item in raw_items:
        item = str(raw_item).strip()
        if item not in result:
            result.append(item)
    return result


class MatcherPriorityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    help_hint: int = Field(default=0, ge=0)
    ai_group_at: int = Field(default=-10, ge=-100)
    ai_mention_guard: int = Field(default=-20, ge=-100)
    server_status: int = Field(default=1, ge=0)
    server_status_admin: int = Field(default=2, ge=0)
    bilibili: int = Field(default=3, ge=0)
    sendpic: int = Field(default=4, ge=0)
    red_packet_notice: int = Field(default=5, ge=0)
    seer_player: int = Field(default=10, ge=0)
    seer_team: int = Field(default=11, ge=0)
    seer_rank: int = Field(default=12, ge=0)
    seer_rank_help: int = Field(default=13, ge=0)
    seer_autocard: int = Field(default=14, ge=0)
    seer_type: int = Field(default=20, ge=0)
    seer_equipment: int = Field(default=21, ge=0)
    seer_peak: int = Field(default=22, ge=0)
    seer_data: int = Field(default=23, ge=0)
    team_resource_subscription: int = Field(default=24, ge=0)
    help: int = Field(default=30, ge=0)
    about: int = Field(default=31, ge=0)
    message_commands: int = Field(default=40, ge=0)
    ai_intent: int = Field(default=50, ge=0)
    meeting: int = Field(default=60, ge=0)
    activity: int = Field(default=70, ge=0)
    db_sync: int = Field(default=80, ge=0)
    team_audit: int = Field(default=90, ge=0)
    seer_mintmark: int = Field(default=100, ge=0)
    seer_pet_config: int = Field(default=109, ge=0)
    seer_pet: int = Field(default=110, ge=0)
    seer_query: int = Field(default=120, ge=0)
    ai_chat: int = Field(default=200, ge=0)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_enabled: bool = False
    file_level: str = "INFO"
    error_file_enabled: bool = False
    rotation: str = "20 MB"
    retention: str = "14 days"
    compression: str | None = "zip"

    @field_validator("file_level")
    @classmethod
    def normalize_file_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in VALID_LOG_LEVELS:
            msg = (
                "bot.logging.file_level must be one of "
                f"{sorted(VALID_LOG_LEVELS)}"
            )
            raise ValueError(msg)
        return level

    @field_validator("rotation", "retention")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot.logging fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("compression", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = "prod"
    driver: str = "~fastapi+~httpx"
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8080, gt=0)
    log_level: str = "INFO"
    command_start: list[str] = Field(default_factory=lambda: ["/", ""])
    superusers: NormalizedIntList = Field(default_factory=list)
    onebot_token: str = Field(default="", exclude=True, repr=False)
    matcher_priority: MatcherPriorityConfig = Field(
        default_factory=MatcherPriorityConfig
    )
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("environment", "driver", "host")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot string fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            msg = f"bot.log_level must be one of {sorted(VALID_LOG_LEVELS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("command_start", mode="before")
    @classmethod
    def normalize_command_start(cls, value: object) -> object:
        return _command_starts(value)

class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_file: Path = Path("logs/ironsbot.log")
    error_log_file: Path = Path("logs/ironsbot.error.log")
    render_cache: Path = Path("render_cache")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: BotConfig = Field(default_factory=BotConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    bilibili: BiliConfig = Field(default_factory=BiliConfig)
    messaging: MessageConfig = Field(default_factory=MessageConfig)
    seer: SeerConfig = Field(default_factory=SeerConfig)
    operations: OperationsConfig = Field(default_factory=OperationsConfig)
