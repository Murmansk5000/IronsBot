# SPDX-License-Identifier: MIT
from ironsbot.config.loader import get_app_config
from ironsbot.config.models.ai import AiConfig


def get_ai_config() -> AiConfig:
    return get_app_config().ai


__all__ = ["AiConfig", "get_ai_config"]
