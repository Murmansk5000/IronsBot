# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
"""OneBot handlers and manifest contribution for Docker maintenance commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.conversations import enter_event_reply_conversation
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
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
from ironsbot.services.operations.docker_update import (
    docker_maintenance_menu_text,
    parse_docker_maintenance_choice,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.startup import StartupNoticeService

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


def _install(registry: MatcherFactory, service: DockerUpdateService) -> None:
    def maintenance_reply(event: MessageEvent) -> bool:
        return event.get_plaintext().strip() in {"0", "1", "2"}

    async def handle_maintenance_choice(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        text = event.get_plaintext().strip()
        if text == "0":
            await finish_event_reply(matcher, event, "已退出机器人维护。")
            return
        choice = parse_docker_maintenance_choice(text)
        if choice is None:
            await finish_event_reply(matcher, event, "序号超出范围，输入 0 退出。")
            return
        message, restart_action = await service.prepare_maintenance(choice)
        await send_event_reply(matcher, event, message)
        await service.execute_restart(restart_action)

    async def open_maintenance_menu(matcher: Matcher, event: MessageEvent) -> None:
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace="docker_maintenance",
            handlers=[handle_maintenance_choice],
            reply_check=maintenance_reply,
            prompt=docker_maintenance_menu_text(),
        )

    async def handle_check_image_update(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.check_image_update(
                progress=partial(send_event_reply, matcher, event)
            ),
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
    restart_matcher.append_handler(open_maintenance_menu)

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
    update_matcher.append_handler(open_maintenance_menu)

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
            visible=partial(superuser_help_visible, features=features),
        ),
        commands=docker_command_contracts(),
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
