from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    db_sync_on_startup: bool = False
    db_sync_interval_enabled: bool = True


plugin_config = get_plugin_config(Config)
