# SPDX-License-Identifier: MIT
from ironsbot.shared.config.config import Config, HelpConfig, get_shared_config

plugin_config = get_shared_config()

__all__ = [
    "Config",
    "HelpConfig",
    "plugin_config",
]
