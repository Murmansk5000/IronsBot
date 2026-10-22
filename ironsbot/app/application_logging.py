# SPDX-License-Identifier: MIT
"""Bridge application logging into the shared, redacted Loguru sinks."""

from __future__ import annotations

import inspect
import logging

from loguru import logger


class ApplicationLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame is not None and (
            depth == 0 or frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_application_logging(level: str) -> None:
    application_logger = logging.getLogger("ironsbot")
    if not any(
        isinstance(handler, ApplicationLogHandler)
        for handler in application_logger.handlers
    ):
        application_logger.addHandler(ApplicationLogHandler())
    application_logger.setLevel(logger.level(level.upper()).no)
    # Root handlers must not receive a second, unredacted copy of the record.
    application_logger.propagate = False
