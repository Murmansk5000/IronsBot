from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.custom_plugins.common.config_utils import nested_json_config
from ironsbot.custom_plugins.common.time_config import (
    normalized_daily_time_csv,
    normalized_daily_times,
)

INVALID_RESTART_TIME_ERROR = (
    "BOT_RESTART_CONFIG.times must contain daily HH:MM times, "
    'for example "04:30,16:10" or ["04:30","16:10"]'
)


class RestartConfig(BaseModel):
    enabled: bool = False
    times: str = "04:30"
    grace_seconds: float = Field(default=10.0, ge=0)
    signal_parent: bool = True

    @field_validator("times", mode="before")
    @classmethod
    def normalize_restart_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RESTART_TIME_ERROR,
        )

    @model_validator(mode="after")
    def validate_restart_times(self) -> Self:
        if self.enabled and not self.parsed_restart_times:
            raise ValueError(INVALID_RESTART_TIME_ERROR)
        return self

    @property
    def parsed_restart_times(self) -> list[str]:
        return normalized_daily_times(
            self.times,
            error_message=INVALID_RESTART_TIME_ERROR,
        )


class Config(BaseModel):
    bot_restart_config: RestartConfig = Field(default_factory=RestartConfig)

    @field_validator("bot_restart_config", mode="before")
    @classmethod
    def normalize_restart_config(cls, value: object) -> object:
        return nested_json_config(value, RestartConfig, name="BOT_RESTART_CONFIG")


plugin_config = get_plugin_config(Config)
