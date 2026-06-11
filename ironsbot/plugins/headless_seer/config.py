# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.shared.config.config import Config, get_shared_config

plugin_config = get_shared_config()

__all__ = [
    "Config",
    "plugin_config",
]
