# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nonebot.log import logger

from ironsbot.config import get_app_config

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import LoggingConfig

_FILE_LOG_SINK_ID: int | None = None


def configure_file_logging(config: LoggingConfig | None = None) -> int | None:
    """Attach an optional rotating file sink to the shared NoneBot logger."""
    global _FILE_LOG_SINK_ID  # noqa: PLW0603

    log_config = config or get_app_config().runtime.logging
    if not log_config.file_enabled:
        return None

    if _FILE_LOG_SINK_ID is not None:
        return _FILE_LOG_SINK_ID

    log_path = Path(log_config.file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _FILE_LOG_SINK_ID = logger.add(
        log_path,
        level=log_config.file_level,
        rotation=log_config.rotation,
        retention=log_config.retention,
        compression=log_config.compression,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    logger.info(f"file logging enabled: {log_path}")
    return _FILE_LOG_SINK_ID


__all__ = ["configure_file_logging"]
