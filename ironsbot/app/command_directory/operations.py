# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.plugins.operations.db_sync import (
    FORCE_MANUAL_SYNC_COMMANDS,
    MANUAL_SYNC_COMMANDS,
)
from ironsbot.plugins.operations.status.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor


def server_status_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "server_status",
            "查询",
            "server_status_query",
            (
                (
                    "server_status.query",
                    (NORMAL_SERVER_STATUS_COMMAND,),
                    "查询当前维护和开服状态",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "server_status",
            "超级管理员",
            None,
            (
                (
                    "server_status.admin_query",
                    (ADMIN_SERVER_STATUS_COMMAND,),
                    "查询开服状态，并在无头未登录时尝试重连",
                    {
                        "features_any": ("server_status_query",),
                        "access": (CommandAccess(audience="superuser"),),
                    },
                ),
            ),
        ),
    )


def docker_update_commands() -> tuple[CommandDescriptor, ...]:
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


def data_sync_commands() -> tuple[CommandDescriptor, ...]:
    return commands_from_rows(
        "db_sync",
        "超级管理员",
        None,
        (
            (
                "db_sync.update",
                tuple(f"/{command}" for command in MANUAL_SYNC_COMMANDS),
                "构建远程数据并同步到机器人",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
            (
                "db_sync.force_update",
                tuple(f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS),
                "忽略本地指纹，强制同步数据",
                {"access": (CommandAccess(audience="superuser"),)},
            ),
        ),
    )
