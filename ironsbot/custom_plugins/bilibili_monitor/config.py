from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    bilibili_monitor_uid: int = 1310714247
    bilibili_monitor_data_dir: Path = Path("data/bilibili_monitor")
    bilibili_monitor_check_interval_minutes: int = 5
    bilibili_monitor_sleep_start_hour: int = 23
    bilibili_monitor_sleep_end_hour: int = 7
    bilibili_monitor_sleep_interval_minutes: int = 30

    bilibili_monitor_target_group_ids: list[int] = Field(default_factory=list)
    bilibili_monitor_target_user_ids: list[int] = Field(default_factory=list)

    bilibili_monitor_admin_uids: list[int] = Field(default_factory=list)


plugin_config = get_plugin_config(Config)
