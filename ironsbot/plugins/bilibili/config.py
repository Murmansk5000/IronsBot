from ironsbot.config.loader import get_app_config
from ironsbot.config.models.bilibili import (
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
)

DEFAULT_SUPPRESS_PATTERNS = DEFAULT_BILI_SUPPRESS_PATTERNS

def get_bili_config() -> BiliConfig:
    return get_app_config().bilibili

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
    "get_bili_config",
]
