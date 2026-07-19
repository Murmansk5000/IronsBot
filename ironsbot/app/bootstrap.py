# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging

import nonebot

from ironsbot.app.composition import Application, build_application
from ironsbot.config.loader import load_settings


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def bootstrap() -> Application:
    configure_third_party_logging()
    settings = load_settings()
    nonebot.init(
        _env_file=(),
        environment=settings.bot.environment,
        driver=settings.bot.driver,
        host=settings.bot.host,
        port=settings.bot.port,
        log_level=settings.bot.log_level,
        command_start=set(settings.bot.command_start),
        superusers={str(value) for value in settings.bot.superusers},
        onebot_access_token=settings.bot.onebot_token or None,
        apscheduler_autostart=False,
    )
    application = build_application(settings)
    application.install()
    return application
