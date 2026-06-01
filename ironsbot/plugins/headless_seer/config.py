# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    headless_seer_login_server_addr: str = "https://seer-login-ip.61.com/unity-ip.txt"
    headless_seer_user_id: int | None = Field(
        default=None, description="米米号", ge=10001
    )
    headless_seer_password: str | None = None
    headless_seer_heartbeat_interval: float = 300
    headless_seer_reconnect_retries: int = -1
    headless_seer_reconnect_delay: float = 5.0
    headless_seer_reconnect_delay_max: float = 120.0


plugin_config = get_plugin_config(Config)
