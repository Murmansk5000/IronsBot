# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import os
from functools import partial
from typing import TYPE_CHECKING

import nonebot
from nonebot.log import LoguruHandler

from ironsbot.app.composition import build_application
from ironsbot.app.nonebot_manifest import nonebot_manifest_path
from ironsbot.config.environment import load_runtime_environment
from ironsbot.config.loader import load_settings
from ironsbot.core.plugin_install import scoped_plugin_install_context

if TYPE_CHECKING:
    from ironsbot.app.application import Application
    from ironsbot.config.models.settings import Settings


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def configure_application_logging(level: str) -> None:
    """Route standard-library application logs through NoneBot's Loguru sink."""

    application_logger = logging.getLogger("ironsbot")
    if not any(
        isinstance(handler, LoguruHandler)
        for handler in application_logger.handlers
    ):
        application_logger.addHandler(LoguruHandler())
    application_logger.setLevel(level.upper())


def initialize_nonebot(settings: Settings) -> None:
    """Initialize NoneBot with the environment selected by the TOML root."""

    variable = "ENVIRONMENT"
    previous = os.environ.get(variable)
    os.environ[variable] = settings.bot.environment
    try:
        nonebot.init(
            _env_file=(),
            environment=settings.bot.environment,
            driver=settings.bot.driver,
            host=settings.bot.host,
            port=settings.bot.port,
            log_level=settings.bot.log_level,
            command_start=set(settings.bot.command_start),
            superusers={str(value) for value in settings.superuser_ids},
            onebot_access_token=settings.bot.onebot_token or None,
            apscheduler_autostart=False,
        )
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous


def bootstrap() -> Application:
    configure_third_party_logging()
    load_runtime_environment()
    settings = load_settings()
    initialize_nonebot(settings)
    configure_application_logging(settings.bot.log_level)
    application = build_application(settings)
    with scoped_plugin_install_context(
        settings=settings,
        resources=application.resources,
        scheduler=application.scheduler,
        extension_contexts=application.extension_contexts,
    ) as context:
        nonebot.load_from_toml(str(nonebot_manifest_path(settings.bot.plugin_manifest)))
        if manifest_path := application.resources.private_extensions.manifest_path:
            with application.resources.private_extensions.plugin_import_path():
                nonebot.load_from_toml(str(manifest_path))
    application.configure(context.contributions)
    if application.resources.qq_official is not None:
        from ironsbot.services.portable_commands import build_portable_command_router

        application.resources.qq_official.bind(
            build_portable_command_router(
                catalog=application.resources.commands,
                contribution_catalog=application.resources.contribution_catalog,
                query_sessions=application.resources.query_sessions,
                ignored_help_plugins=tuple(settings.features.help.ignored_plugins),
                about=application.resources.about,
                seer=application.resources.seer,
                player_id_resolver=application.resources.player_id_resolver,
                identity_links=application.resources.identity_links,
                identity_linking=application.resources.identity_linking,
                features=application.resources.features,
                ai=application.resources.ai,
                ai_intent_actions=application.resources.ai_intent_actions,
                addressed_input_hints=application.resources.addressed_input_hints,
                team_resource=application.resources.team_resource,
                lucky_skin_window=application.resources.lucky_skin_window,
                activity=application.resources.activity,
                messaging=application.resources.messaging,
                refresh_push_time_jobs=partial(
                    application.resources.messaging.refresh_push_time_jobs,
                    scheduler=application.scheduler,
                    activity_service=application.resources.activity,
                ),
                sendpic=application.resources.sendpic,
                bilibili=application.resources.bilibili,
                bilibili_monitor=application.resources.bilibili_monitor,
                server_status=application.resources.server_status,
                data_sync=application.resources.data_sync,
                docker_update=application.resources.docker_update,
                meeting_number=settings.messaging.meeting.number,
                meeting_template=settings.messaging.meeting.template,
                pet_config=application.resources.pet_config,
                image_command_texts=(
                    application.resources.sendpic.exact_command_texts
                ),
                new_content_expanded_categories=frozenset(
                    settings.seer.new_content.expanded_categories
                ),
                new_content_preview_max_items=(
                    settings.seer.new_content.auto_expand_max_items
                ),
            ),
            application.resources.outbound_messenger,
        )
    application.install()
    return application
