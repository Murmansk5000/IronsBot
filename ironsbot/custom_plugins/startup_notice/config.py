from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    startup_notice_enabled: bool = True
    startup_notice_users: list[int] = Field(default_factory=list)
    startup_notice_message: str = "机器人已开启。"
    startup_notice_delay_seconds: float = Field(default=3.0, ge=0)


plugin_config = get_plugin_config(Config)
