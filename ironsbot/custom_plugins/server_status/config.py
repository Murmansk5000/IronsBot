# SPDX-License-Identifier: MIT
from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.runtime import (
    DEFAULT_BROADCAST_MESSAGE,
    ServerStatusConfig,
)

Config = AppConfig


def get_server_status_config() -> ServerStatusConfig:
    return get_app_config().runtime.server_status

__all__ = [
    "DEFAULT_BROADCAST_MESSAGE",
    "Config",
    "ServerStatusConfig",
    "get_server_status_config",
]
