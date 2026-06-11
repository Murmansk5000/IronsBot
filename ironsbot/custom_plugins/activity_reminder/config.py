# SPDX-License-Identifier: MIT
from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.activity import ActivityConfig

Config = AppConfig


def get_activity_config() -> ActivityConfig:
    return get_app_config().activity


__all__ = ["ActivityConfig", "Config", "get_activity_config"]
