import json
from collections.abc import Sequence

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

INVALID_RESTART_TIME_ERROR = (
    "bot_restart_times must contain daily HH:MM times, "
    'for example "04:30,16:10" or ["04:30","16:10"]'
)
RESTART_TIME_PARTS = 2
MIN_HOUR = 0
MAX_HOUR = 23
MIN_MINUTE = 0
MAX_MINUTE = 59


def _normalize_restart_time(value: object) -> str:
    if not isinstance(value, str):
        value = str(value)

    text = value.strip()
    parts = text.split(":")
    if len(parts) != RESTART_TIME_PARTS:
        raise ValueError(INVALID_RESTART_TIME_ERROR)

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(INVALID_RESTART_TIME_ERROR) from exc

    if not MIN_HOUR <= hour <= MAX_HOUR or not MIN_MINUTE <= minute <= MAX_MINUTE:
        raise ValueError(INVALID_RESTART_TIME_ERROR)

    return f"{hour:02d}:{minute:02d}"


def _split_restart_times(value: object) -> list[object]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []

        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(INVALID_RESTART_TIME_ERROR) from exc
            return _split_restart_times(parsed)

        return [
            part.strip()
            for part in text.replace("，", ",").replace("；", ",").split(",")
            if part.strip()
        ]

    if isinstance(value, Sequence):
        return list(value)

    return [value]


class Config(BaseModel):
    bot_restart_enabled: bool = False
    bot_restart_times: str = "04:30"
    bot_restart_grace_seconds: float = Field(default=10.0, ge=0)
    bot_restart_signal_parent: bool = True

    @field_validator("bot_restart_times", mode="before")
    @classmethod
    def normalize_restart_times(cls, value: object) -> str:
        times = [_normalize_restart_time(item) for item in _split_restart_times(value)]
        return ",".join(sorted(dict.fromkeys(times)))

    @model_validator(mode="after")
    def validate_restart_times(self) -> Self:
        if self.bot_restart_enabled and not self.parsed_restart_times:
            raise ValueError(INVALID_RESTART_TIME_ERROR)
        return self

    @property
    def parsed_restart_times(self) -> list[str]:
        return [
            _normalize_restart_time(item)
            for item in _split_restart_times(self.bot_restart_times)
        ]


plugin_config = get_plugin_config(Config)
