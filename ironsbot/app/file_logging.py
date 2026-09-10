# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.log import logger


class RankLogHandler(logging.Handler):
    """Forward only first-party rank evidence, not HTTP/authentication logs."""

    def emit(self, record: logging.LogRecord) -> None:
        if not (
            record.name.startswith("ironsbot.services.seer.rank")
            or record.name.startswith("ironsbot.integrations.headless_seer.rank")
            or record.name == "ironsbot.integrations.storage.rank_page_cache"
        ):
            return
        logger.opt(exception=record.exc_info).log(record.levelname, record.getMessage())


if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.config.models.settings import LoggingConfig, PathsConfig


@dataclass(slots=True)
class FileLogging:
    sink_ids: list[int] = field(default_factory=list)
    rank_handlers: list[tuple[logging.Logger, logging.Handler, int]] = field(
        default_factory=list
    )

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
        for name in (
            "ironsbot.services.seer",
            "ironsbot.integrations.headless_seer.rank",
            "ironsbot.integrations.headless_seer.rank_wire",
            "ironsbot.integrations.storage.rank_page_cache",
        ):
            source = logging.getLogger(name)
            handler = RankLogHandler()
            resource.rank_handlers.append((source, handler, source.level))
            source.setLevel(logging.INFO)
            source.addHandler(handler)
        return resource

    def close(self) -> None:
        while self.rank_handlers:
            source, handler, level = self.rank_handlers.pop()
            source.removeHandler(handler)
            source.setLevel(level)
            handler.close()
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
