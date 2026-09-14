from __future__ import annotations

import logging

from nonebot.log import LoguruHandler, logger

from ironsbot.app.logging_setup import configure_project_logging


def test_project_stdlib_logging_is_bridged_once() -> None:
    project_logger = logging.getLogger("ironsbot")
    original_handlers = list(project_logger.handlers)
    original_level = project_logger.level
    original_propagate = project_logger.propagate
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    try:
        project_logger.handlers.clear()
        configure_project_logging("INFO")
        configure_project_logging("INFO")

        logging.getLogger("ironsbot.acceptance").info("official connection ready")

        assert len(
            [
                handler
                for handler in project_logger.handlers
                if isinstance(handler, LoguruHandler)
            ]
        ) == 1
        assert sum("official connection ready" in message for message in messages) == 1
        assert project_logger.level == logging.INFO
        assert not project_logger.propagate
    finally:
        logger.remove(sink_id)
        project_logger.handlers[:] = original_handlers
        project_logger.setLevel(original_level)
        project_logger.propagate = original_propagate
