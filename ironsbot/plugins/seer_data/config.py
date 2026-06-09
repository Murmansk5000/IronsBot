# SPDX-License-Identifier: MIT
from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    seerapi_sync_url: str = (
        "https://github.com/Murmansk5000/seerapi/releases/download/"
        "ironsbot-data-latest/ironsbot-data.sqlite"
    )
    seerapi_fingerprint_url: str = (
        "https://github.com/Murmansk5000/seerapi/releases/download/"
        "ironsbot-data-latest/ironsbot-data.sqlite.sha256"
    )
    seerapi_sync_interval_minutes: int = 60
    seerapi_local_path: str = "data/ironsbot-data.sqlite"
    alias_sync_url: str = (
        "https://github.com/Murmansk5000/seerapi/releases/download/"
        "alias-db-latest/aliases-data.sqlite"
    )
    alias_fingerprint_url: str = (
        "https://github.com/Murmansk5000/seerapi/releases/download/"
        "alias-db-latest/aliases-data.sqlite.sha256"
    )
    alias_sync_interval_minutes: int = 60
    alias_local_path: str = "data/aliases-data.sqlite"


plugin_config = get_plugin_config(Config)
