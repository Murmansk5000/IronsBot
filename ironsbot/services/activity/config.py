# SPDX-License-Identifier: MIT
from ironsbot.config.loader import get_app_config
from ironsbot.config.models.activity import ActivityConfig


def get_activity_config() -> ActivityConfig:
    return get_app_config().activity


__all__ = ["ActivityConfig", "get_activity_config"]
