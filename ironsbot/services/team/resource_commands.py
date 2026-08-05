# SPDX-License-Identifier: MIT
"""Command contracts owned by team-resource subscriptions."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)


def team_resource_command_descriptors(
    *,
    enabled: bool,
) -> tuple[CommandDescriptor, ...]:
    """Describe query and subscription management commands when enabled."""

    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "team_resource",
            "查询",
            "team_resource_subscription",
            (
                (
                    "team_resource.query",
                    ("战队",),
                    "查看当前会话订阅战队的信息和资源",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "team_resource",
            "订阅管理",
            "team_resource_subscription",
            (
                (
                    "team_resource.subscribe",
                    ("订阅战队123456",),
                    "订阅战队资源提醒；群聊可在末尾 @ 提醒对象",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
                (
                    "team_resource.unsubscribe",
                    ("取消订阅战队123456",),
                    "取消当前会话指定战队订阅",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
                (
                    "team_resource.list",
                    ("战队订阅",),
                    "查看和管理当前会话的战队订阅",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
            ),
        ),
    )
