import json
from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    bilibili_monitor_uid: int = 1310714247
    bilibili_monitor_uids: list[int] = Field(default_factory=list)
    bilibili_monitor_data_dir: Path = Path("data/bilibili_monitor")
    bilibili_monitor_check_interval_minutes: int = 5
    bilibili_monitor_sleep_start_hour: int = 23
    bilibili_monitor_sleep_end_hour: int = 7
    bilibili_monitor_sleep_interval_minutes: int = 30

    bilibili_monitor_target_group_ids: list[int] = Field(default_factory=list)
    bilibili_monitor_target_user_ids: list[int] = Field(default_factory=list)

    @field_validator("bilibili_monitor_uids", mode="before")
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
