# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import os
import time
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.application_logging import configure_application_logging
from ironsbot.app.composition import build_application
from ironsbot.app.log_privacy import configure_log_privacy
from ironsbot.app.plugin_composition import build_builtin_contributions
from ironsbot.config.environment import load_runtime_environment
from ironsbot.config.loader import load_settings

APPLICATION_TIMEZONE = "Asia/Shanghai"

if TYPE_CHECKING:
    from ironsbot.app.application import Application


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def configure_process_timezone() -> None:
    """Keep framework logs and third-party local clocks on Beijing time."""

    os.environ["TZ"] = APPLICATION_TIMEZONE
    tzset = getattr(time, "tzset", None)
    if tzset is not None:
        tzset()


def bootstrap() -> Application:
    configure_third_party_logging()
    load_runtime_environment()
    configure_process_timezone()
    configure_log_privacy(os.environ)
    settings = load_settings()
    configure_application_logging(settings.bot.log_level)
    application = build_application(settings)
    contributions = build_builtin_contributions(
        settings, application.resources, application.scheduler
    )
    private_contributions = application.resources.private_extensions.contributions(
        application.extension_services
    )
    application.configure(contributions + private_contributions)
    from ironsbot.integrations.storage.inbound_claims import SqliteInboundMessageClaims
    from ironsbot.services.portable_commands import build_portable_command_router

    router = build_portable_command_router(
        catalog=application.resources.commands,
        contribution_catalog=application.resources.contribution_catalog,
        query_sessions=application.resources.query_sessions,
        ignored_help_plugins=tuple(settings.features.help.ignored_plugins),
        about=application.resources.about,
        seer=application.resources.seer,
        player_id_resolver=application.resources.player_id_resolver,
        identity_links=application.resources.identity_links,
        identity_principals=application.resources.identity_principals,
        identity_observer=application.resources.identity_observer,
        union_identity=application.resources.union_identity,
        inbound_claims=SqliteInboundMessageClaims(
            settings.paths.cache_root / "qq_official" / "inbound.sqlite",
            spawn=application.task_owner.create_draining,
        ),
        features=application.resources.features,
        ai=application.resources.ai,
        ai_intent_actions=application.resources.ai_intent_actions,
        addressed_input_hints=application.resources.addressed_input_hints,
        admin_notices=application.resources.admin_notices,
        errors=application.resources.command_errors,
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
        image_command_texts=application.resources.sendpic.exact_command_texts,
        new_content_expanded_categories=frozenset(
            settings.seer.new_content.expanded_categories
        ),
        new_content_preview_max_items=settings.seer.new_content.auto_expand_max_items,
    )
    if application.resources.qq_official is not None:
        application.resources.qq_official.bind(
            router,
            application.resources.outbound_messenger,
        )
    application.install(router)
    return application
