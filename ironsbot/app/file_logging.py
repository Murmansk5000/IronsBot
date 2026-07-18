# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nonebot.log import logger

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import LoggingConfig

_FILE_LOG_SINK_ID: int | None = None
_ERROR_FILE_LOG_SINK_ID: int | None = None


def configure_file_logging(config: LoggingConfig) -> int | None:
    """Attach an optional rotating file sink to the shared NoneBot logger."""
    global _ERROR_FILE_LOG_SINK_ID, _FILE_LOG_SINK_ID  # noqa: PLW0603

    if not config.file_enabled:
        return None

    if _FILE_LOG_SINK_ID is not None:
        return _FILE_LOG_SINK_ID

    log_path = Path(config.file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _FILE_LOG_SINK_ID = logger.add(
        log_path,
        level=config.file_level,
        rotation=config.rotation,
        retention=config.retention,
        compression=config.compression,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    logger.info(f"file logging enabled: {log_path}")

    if config.error_file_enabled:
        error_log_path = Path(config.error_file_path)
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        _ERROR_FILE_LOG_SINK_ID = logger.add(
            error_log_path,
            level="ERROR",
            rotation=config.rotation,
            retention=config.retention,
            compression=config.compression,
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            diagnose=False,
        )
        logger.info(f"error file logging enabled: {error_log_path}")

    return _FILE_LOG_SINK_ID


__all__ = ["configure_file_logging"]
