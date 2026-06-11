# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.seer import RenderConfig

Config = AppConfig


def get_render_config() -> RenderConfig:
    return get_app_config().seer.render

__all__ = [
    "Config",
    "RenderConfig",
    "get_render_config",
]
