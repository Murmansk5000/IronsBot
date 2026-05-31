# SPDX-License-Identifier: MIT
from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    seerapi_sync_url: str = ""
    seerapi_fingerprint_url: str = ""
    seerapi_sync_interval_minutes: int = 60
    seerapi_local_path: str = "data/seerapi-data.sqlite"
    alias_sync_url: str = ""
    alias_fingerprint_url: str = ""
    alias_sync_interval_minutes: int = 60
    alias_local_path: str = "data/aliases-data.sqlite"


plugin_config = get_plugin_config(Config)
