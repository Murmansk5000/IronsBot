from ironsbot.shared.config.config import (
    DEFAULT_BILI_SUPPRESS_PATTERNS,
    INVALID_INTERVAL_TIME_ERROR,
    BiliConfig,
    BiliFilterConfig,
    BiliIntervalWindow,
    BiliPollingConfig,
    BiliPushConfig,
    BiliPushMode,
    BiliPushTargetConfig,
    BiliStorageConfig,
    Config,
    get_shared_config,
)

DEFAULT_SUPPRESS_PATTERNS = DEFAULT_BILI_SUPPRESS_PATTERNS
plugin_config = get_shared_config()

__all__ = [
    "DEFAULT_SUPPRESS_PATTERNS",
    "INVALID_INTERVAL_TIME_ERROR",
    "BiliConfig",
    "BiliFilterConfig",
    "BiliIntervalWindow",
    "BiliPollingConfig",
    "BiliPushConfig",
    "BiliPushMode",
    "BiliPushTargetConfig",
    "BiliStorageConfig",
    "Config",
    "plugin_config",
]
