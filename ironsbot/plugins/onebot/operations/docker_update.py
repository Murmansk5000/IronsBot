# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""OneBot handlers and manifest contribution for Docker maintenance commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from ironsbot.runtime.commands import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.onebot_identity import onebot_actor_ref
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)

from .status.command_text import (
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.features import FeatureService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.startup import StartupNoticeService

__plugin_meta__ = PluginMetadata(
    name="镜像维护",
    description="检查或更新 Docker 镜像，并重启机器人进程。",
    usage="超级管理员可发送“/检查更新镜像”“/更新镜像”或“/重启机器人”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def command_descriptors() -> tuple[CommandDescriptor, ...]:
    return commands_from_rows(
        "docker_update",
        "超级管理员",
        None,
        (
            (
                "docker_update.restart",
                BOT_RESTART_COMMANDS,
                "重启机器人进程",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
            (
                "docker_update.image_update",
                DOCKER_UPDATE_COMMANDS,
                "检查镜像并重启机器人",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
            (
                "docker_update.image_check",
                DOCKER_CHECK_UPDATE_COMMANDS,
                "只检查远端镜像，不拉取或重启机器人",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
        ),
    )


def _help_visible(event: Event, *, features: FeatureService) -> bool:
    if isinstance(event, GroupMessageEvent):
        return False
    user_id = getattr(event, "user_id", None)
    return user_id is not None and features.is_actor_superuser(
        onebot_actor_ref(str(user_id))
    )


def _start_docker_update(*, startup_notice: StartupNoticeService) -> None:
    startup_notice.add(
        "startup_docker_update",
        "startup docker update notice",
        consume_docker_startup_preflight_notice(),
    )


def _install(registry: MatcherRegistry, service: DockerUpdateService) -> None:
    async def handle_restart(matcher: Matcher, event: MessageEvent) -> None:
        message, restart_action = await service.prepare_manual_restart()
        await send_event_reply(matcher, event, message)
        await service.execute_restart(restart_action)

    async def handle_check_image_update(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.check_image_update(),
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
    restart_matcher.append_handler(handle_restart)

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
    update_matcher.append_handler(handle_restart)

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
    check_update_matcher.append_handler(handle_check_image_update)


def plugin_contribution(
    *,
    service: DockerUpdateService,
    features: FeatureService,
    startup_notice: StartupNoticeService,
) -> PluginContribution:
    """Declare Docker maintenance commands and startup preflight reporting."""

    return PluginContribution(
        id="docker_update",
        help=HelpEntry(
            name="镜像维护",
            description="检查 Docker 镜像、更新镜像或重启机器人",
            group="admin",
            order=10,
            visible=partial(_help_visible, features=features),
        ),
        commands=command_descriptors(),
        install=partial(_install, service=service),
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
        ),
    )
