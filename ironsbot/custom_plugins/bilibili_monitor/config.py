import json
from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    bili_uid: int = 1310714247
    bili_uids: list[int] = Field(default_factory=list)
    bili_data_dir: Path = Path("data/bilibili_monitor")
    bili_check_minutes: int = 5
    bili_sleep_start: int = 23
    bili_sleep_end: int = 7
    bili_sleep_minutes: int = 30

    bili_groups: list[int] = Field(default_factory=list)
    bili_users: list[int] = Field(default_factory=list)

    @field_validator("bili_uids", mode="before")
    @classmethod
    def normalize_monitor_uids(cls, value: object) -> object:
        if value is None or value == "":
            return []

        if isinstance(value, int):
            return [value]

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []

            if text.startswith("["):
                return json.loads(text)

            return [
                int(item.strip())
                for item in text.split(",")
                if item.strip()
            ]

        return value


plugin_config = get_plugin_config(Config)
