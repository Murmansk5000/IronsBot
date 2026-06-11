from ironsbot.config import AppConfig, get_app_config
from ironsbot.config.models.runtime import (
    INVALID_RECONNECT_TIME_ERROR,
    HeadlessNoticeConfig,
)

Config = AppConfig


def get_headless_notice_config() -> HeadlessNoticeConfig:
    return get_app_config().runtime.headless_notice

__all__ = [
    "INVALID_RECONNECT_TIME_ERROR",
    "Config",
    "HeadlessNoticeConfig",
    "get_headless_notice_config",
]
