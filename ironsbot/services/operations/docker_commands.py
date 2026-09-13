# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for Docker maintenance."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
)
from ironsbot.services.operations.command_text import (
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
)


def docker_command_contracts() -> tuple[CommandContract, ...]:
    """Describe Docker maintenance commands for the shared command catalog."""

    return commands_from_rows(
        "docker_update",
        "超级管理员",
        None,
        (
            (
                "docker_update.restart",
                BOT_RESTART_COMMANDS,
                "打开维护菜单，选择仅重启或更新镜像后重启",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
            (
                "docker_update.image_update",
                DOCKER_UPDATE_COMMANDS,
                "打开维护菜单，选择仅重启或更新镜像后重启",
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
