from ironsbot.config.loader import get_app_config
from ironsbot.config.models.runtime import (
    INVALID_RECONNECT_TIME_ERROR,
    HeadlessNoticeConfig,
)


def get_headless_notice_config() -> HeadlessNoticeConfig:
    return get_app_config().runtime.headless_notice


__all__ = [
    "INVALID_RECONNECT_TIME_ERROR",
    "HeadlessNoticeConfig",
    "get_headless_notice_config",
]
