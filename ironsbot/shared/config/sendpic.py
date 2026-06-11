# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import PicConfig, SendpicConfig


def pic_id_is_enabled(config: SendpicConfig, pic_id: str) -> bool:
    return pic_id in config.enabled_ids


def enabled_pic_configs(config: SendpicConfig) -> list[PicConfig]:
    return [
        pic_config
        for pic_config in config.configs
        if pic_id_is_enabled(config, pic_config.id)
    ]
