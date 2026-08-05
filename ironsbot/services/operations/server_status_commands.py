# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for server-status operations."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.services.operations.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    HEADLESS_INSTANCE_STATUS_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)


def server_status_command_descriptors() -> tuple[CommandDescriptor, ...]:
    """Describe server-status commands for the shared command catalog."""

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
                (
                    "server_status.headless_instances",
                    HEADLESS_INSTANCE_STATUS_COMMANDS,
                    "查看公共查询池与临时专用会话的当前在线实例数",
                    {
                        "access": (
                            CommandAccess(scope="private", audience="superuser"),
                        )
                    },
                ),
            ),
        ),
    )
