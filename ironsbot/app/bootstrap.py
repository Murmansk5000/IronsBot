# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING

import nonebot

from ironsbot.app.composition import build_application
from ironsbot.app.logging_setup import configure_project_logging
from ironsbot.app.nonebot_manifest import nonebot_manifest_path
from ironsbot.config.loader import load_settings
from ironsbot.core.plugin_install import scoped_plugin_install_context

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.app.application import Application


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


@contextmanager
def _nonebot_environment(environment: str) -> Iterator[None]:
    """Expose the TOML environment label while NoneBot constructs its Env."""

    key = "ENVIRONMENT"
    previous = os.environ.get(key)
    os.environ[key] = environment
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def bootstrap() -> Application:
    configure_third_party_logging()
    settings = load_settings()
    with _nonebot_environment(settings.bot.environment):
        nonebot.init(
            _env_file=(),
            driver=settings.bot.driver,
            host=settings.bot.host,
            port=settings.bot.port,
            log_level=settings.bot.log_level,
            command_start=set(settings.bot.command_start),
            superusers={str(value) for value in settings.superuser_ids},
            onebot_access_token=settings.bot.onebot_token or None,
            apscheduler_autostart=False,
        )
    configure_project_logging(settings.bot.log_level)
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
                about=application.resources.about,
                seer=application.resources.seer,
                player_id_resolver=application.resources.player_id_resolver,
                features=application.resources.features,
                ai=application.resources.ai,
                team_resource=application.resources.team_resource,
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
                lucky_skin_window=application.resources.lucky_skin_window,
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
                query_sessions=application.resources.query_sessions,
                ignored_help_plugins=tuple(
                    settings.features.help.ignored_plugins
                ),
            ),
            application.resources.outbound_messenger,
        )
    application.install()
    return application
