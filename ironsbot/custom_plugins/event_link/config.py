from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    event_link_text: str = (
        "周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign"
    )
    event_link_reply_groups: list[int] = Field(default_factory=list)
    event_link_reply_users: list[int] = Field(default_factory=list)
    event_link_send_groups: list[int] = Field(default_factory=list)
    event_link_send_users: list[int] = Field(default_factory=list)
    event_link_send_hour: int = 23
    event_link_send_minute: int = 0


plugin_config = get_plugin_config(Config)
