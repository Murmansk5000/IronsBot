# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.core.commands import csv_items, int_list, json_array


def command_start_list(value: object) -> list[str]:
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


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    environment: str = "prod"
    driver: str = "~fastapi+~httpx"
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8080, gt=0)
    log_level: str = "INFO"
    command_start: list[str] = Field(default_factory=lambda: ["/", ""])
    superusers: list[int] = Field(default_factory=list)
    app_config_path: str | None = None

    @field_validator("command_start", mode="before")
    @classmethod
    def normalize_command_start(cls, value: object) -> object:
        return command_start_list(value)

    @field_validator("superusers", mode="before")
    @classmethod
    def normalize_superusers(cls, value: object) -> object:
        return int_list(value)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.strip().upper() or "INFO"
