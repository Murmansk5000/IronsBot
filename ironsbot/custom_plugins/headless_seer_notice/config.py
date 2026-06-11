from ironsbot.shared.config.config import (
    INVALID_RECONNECT_TIME_ERROR,
    Config,
    HeadlessNoticeConfig,
    get_shared_config,
)

plugin_config = get_shared_config()

__all__ = [
    "INVALID_RECONNECT_TIME_ERROR",
    "Config",
    "HeadlessNoticeConfig",
    "plugin_config",
]
