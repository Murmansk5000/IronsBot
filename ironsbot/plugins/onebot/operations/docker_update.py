# SPDX-License-Identifier: MIT
"""OneBot handlers and manifest contribution for Docker maintenance commands."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
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


def plugin_contribution(
    *, features: FeatureService, startup_notice: StartupNoticeService
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
            features=context.resources.features,
            startup_notice=context.resources.startup_notice,
        ),
    )
