# SPDX-License-Identifier: MIT
"""OneBot handlers and manifest contribution for Docker maintenance commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.command_text import (
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
)
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)
from ironsbot.services.portable_operational_commands import (
    build_portable_docker_operations,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.startup import StartupNoticeService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions

__plugin_meta__ = PluginMetadata(
    name="镜像维护",
    description="检查或更新 Docker 镜像，并重启机器人进程。",
    usage="超级管理员可发送“/检查更新镜像”，或打开“/重启机器人”维护菜单。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def _start_docker_update(*, startup_notice: StartupNoticeService) -> None:
    startup_notice.add(
        "startup_docker_update",
        "startup docker update notice",
        consume_docker_startup_preflight_notice(),
    )


def _install(
    registry: MatcherFactory,
    service: DockerUpdateService,
    query_sessions: PortableQuerySessions,
) -> None:
    operations = build_portable_docker_operations(service, query_sessions)
    restart_handler = make_portable_query_handler(
        operations["docker_update.restart"],
        query_sessions,
        ActionDefinition("docker_maintenance", "机器人维护"),
    )
    update_handler = make_portable_query_handler(
        operations["docker_update.image_update"],
        query_sessions,
        ActionDefinition("docker_maintenance", "机器人维护"),
    )

    restart_matcher = registry.on_fullmatch(
        BOT_RESTART_COMMANDS,
        policy=CommandPolicy.command(
            "bot_restart",
            help_ids=("docker_update.restart",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    restart_matcher.append_handler(restart_handler)

    update_matcher = registry.on_fullmatch(
        DOCKER_UPDATE_COMMANDS,
        policy=CommandPolicy.command(
            "bot_restart",
            help_ids=("docker_update.image_update",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    update_matcher.append_handler(update_handler)

    check_update_matcher = registry.on_fullmatch(
        DOCKER_CHECK_UPDATE_COMMANDS,
        policy=CommandPolicy.command(
            "bot_restart",
            help_ids=("docker_update.image_check",),
        ),
        rule=explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("server_status_admin"),
        block=True,
    )
    check_update_matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["docker_update.image_check"],
        )
    )


def plugin_contribution(
    *,
    service: DockerUpdateService,
    features: FeatureService,
    startup_notice: StartupNoticeService,
    query_sessions: PortableQuerySessions,
) -> PluginContribution:
    """Declare Docker maintenance commands and startup preflight reporting."""

    return PluginContribution(
        id="docker_update",
        help=HelpEntry(
            name="镜像维护",
            description="检查 Docker 镜像、更新镜像或重启机器人",
            group="admin",
            order=10,
            visible=partial(superuser_help_visible, features=features),
        ),
        commands=docker_command_contracts(),
        install=partial(
            _install,
            service=service,
            query_sessions=query_sessions,
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "docker_update",
                    partial(_start_docker_update, startup_notice=startup_notice),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.docker_update,
            features=context.resources.features,
            startup_notice=context.resources.startup_notice,
            query_sessions=context.resources.query_sessions,
        ),
    )
