# SPDX-License-Identifier: MIT
"""Command contracts owned by team-resource subscriptions."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
    normalized_command_input_matcher,
    parsed_command_input_matcher,
)
from ironsbot.services.team.resource_subscriptions import (
    parse_team_resource_manage_command,
)


def team_resource_command_contracts(
    *,
    enabled: bool,
    query_commands: tuple[str, ...],
) -> tuple[CommandContract, ...]:
    """Describe query and subscription management commands when enabled."""

    if not enabled:
        return ()
    matches_query = normalized_command_input_matcher(query_commands)
    return (
        *commands_from_rows(
            "team_resource",
            "查询",
            "team_resource_subscription",
            (
                (
                    "team_resource.query",
                    query_commands,
                    "查看绑定战队和当前会话订阅战队的概览，输入编号查看详情",
                    {
                        "show_in_poke": True,
                        "routing_matcher": lambda text, context: (
                            not context.has_member_mentions
                            and matches_query(text, context)
                        ),
                    },
                ),
            )
            if query_commands
            else (),
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
                        "routing_matcher": parsed_command_input_matcher(
                            parse_team_resource_manage_command,
                            accepts=lambda command: command.action == "add",
                        ),
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
                        "routing_matcher": parsed_command_input_matcher(
                            parse_team_resource_manage_command,
                            accepts=lambda command: command.action == "remove",
                        ),
                    },
                ),
                (
                    "team_resource.list",
                    ("战队订阅",),
                    "查看当前会话的战队订阅",
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            parse_team_resource_manage_command,
                            accepts=lambda command: command.action == "list",
                        ),
                    },
                ),
            ),
        ),
    )
