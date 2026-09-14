# SPDX-License-Identifier: MIT
"""Route project-owned stdlib logs through NoneBot's Loguru sinks."""

from __future__ import annotations

import logging

from nonebot.log import LoguruHandler

_PROJECT_LOGGER = "ironsbot"


def configure_project_logging(level: str) -> None:
    """Install one Loguru bridge for every ``ironsbot.*`` stdlib logger."""

    project_logger = logging.getLogger(_PROJECT_LOGGER)
    if not any(
        isinstance(handler, LoguruHandler) for handler in project_logger.handlers
    ):
        project_logger.addHandler(LoguruHandler())
    project_logger.setLevel(level.upper())
    project_logger.propagate = False
