# SPDX-License-Identifier: MIT
"""Shared command and lifecycle contribution for Docker maintenance."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.docker_preflight import (
    consume_docker_startup_preflight_notice,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.startup import StartupNoticeService


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
