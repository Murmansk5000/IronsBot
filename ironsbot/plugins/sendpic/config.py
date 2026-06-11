# SPDX-License-Identifier: MIT
from ironsbot.shared.config.config import (
    DEFAULT_SENDPIC_MESSAGE_TEMPLATE,
    Config,
    PicConfig,
    SendpicBackendType,
    get_shared_config,
)

BackendType = SendpicBackendType
DEFAULT_MESSAGE_TEMPLATE = DEFAULT_SENDPIC_MESSAGE_TEMPLATE
plugin_config = get_shared_config()


__all__ = [
    "DEFAULT_MESSAGE_TEMPLATE",
    "BackendType",
    "Config",
    "PicConfig",
    "plugin_config",
]
