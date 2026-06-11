# SPDX-License-Identifier: MIT
from ironsbot.shared.config.config import (
    BiliConfig,
    BiliFilterConfig,
    BiliIntervalWindow,
    BiliPollingConfig,
    BiliPushConfig,
    BiliPushMode,
    BiliPushTargetConfig,
    BiliStorageConfig,
)


class BilibiliConfig(BiliConfig):
    pass


__all__ = [
    "BiliFilterConfig",
    "BiliIntervalWindow",
    "BiliPollingConfig",
    "BiliPushConfig",
    "BiliPushMode",
    "BiliPushTargetConfig",
    "BiliStorageConfig",
    "BilibiliConfig",
]
