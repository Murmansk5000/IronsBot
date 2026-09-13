# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import nonebot

from ironsbot.app.composition import build_application
from ironsbot.app.nonebot_manifest import nonebot_manifest_path
from ironsbot.config.loader import load_settings
from ironsbot.core.plugin_install import scoped_plugin_install_context

if TYPE_CHECKING:
    from ironsbot.app.application import Application


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def bootstrap() -> Application:
    configure_third_party_logging()
    settings = load_settings()
    qq_official = settings.bot.qq_official
    qq_bots = (
        [
            {
                "id": qq_official.app_id,
                # adapter-qq 1.7.2 still declares the retired static token field,
                # but authentication uses AppID + AppSecret to refresh AccessToken.
                "token": "",
                "secret": qq_official.secret,
                "use_websocket": True,
                "intent": {"c2c_group_at_messages": True},
            }
        ]
        if qq_official.enabled
        else []
    )
    nonebot.init(
        _env_file=(),
        environment=settings.bot.environment,
        driver=settings.bot.effective_driver,
        host=settings.bot.host,
        port=settings.bot.port,
        log_level=settings.bot.log_level,
        command_start=set(settings.bot.command_start),
        superusers={str(value) for value in settings.superuser_ids},
        onebot_access_token=settings.bot.onebot_token or None,
        qq_bots=qq_bots,
        qq_is_sandbox=qq_official.sandbox,
        apscheduler_autostart=False,
    )
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
    if qq_official.enabled:
        from ironsbot.integrations.qq_official.runtime import (
            install_qq_official_runtime,
        )
        from ironsbot.services.portable_commands import build_portable_command_router

        install_qq_official_runtime(
            build_portable_command_router(
                catalog=application.resources.commands,
                about=application.resources.about,
                seer=application.resources.seer,
                player_id_resolver=application.resources.player_id_resolver,
                features=application.resources.features,
                ai=application.resources.ai,
                team_resource=application.resources.team_resource,
                activity=application.resources.activity,
                messaging=application.resources.messaging,
                sendpic=application.resources.sendpic,
                bilibili=application.resources.bilibili,
                bilibili_monitor=application.resources.bilibili_monitor,
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
