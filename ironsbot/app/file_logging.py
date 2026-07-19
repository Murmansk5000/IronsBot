# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.log import logger

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.config.models.settings import LoggingConfig, PathsConfig


@dataclass(slots=True)
class FileLogging:
    sink_ids: list[int] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        config: LoggingConfig,
        paths: PathsConfig,
    ) -> FileLogging:
        resource = cls()
        if not config.file_enabled:
            return resource

        resource._add_sink(paths.log_file, config, level=config.file_level)
        logger.info(f"file logging enabled: {paths.log_file}")
        if config.error_file_enabled:
            resource._add_sink(paths.error_log_file, config, level="ERROR")
            logger.info(f"error file logging enabled: {paths.error_log_file}")
        return resource

    def close(self) -> None:
        while self.sink_ids:
            logger.remove(self.sink_ids.pop())

    def _add_sink(
        self,
        path: Path,
        config: LoggingConfig,
        *,
        level: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.sink_ids.append(
            logger.add(
                path,
                level=level,
                rotation=config.rotation,
                retention=config.retention,
                compression=config.compression,
                encoding="utf-8",
                enqueue=True,
                backtrace=True,
                diagnose=False,
            )
        )
