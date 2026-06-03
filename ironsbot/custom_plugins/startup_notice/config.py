from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    startup_notice: bool = True
    startup_message: str = "机器人已开启。"
    startup_delay: float = Field(default=0.0, ge=0)


plugin_config = get_plugin_config(Config)
