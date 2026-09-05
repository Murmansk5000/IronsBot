# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for Bilibili dynamic features."""

from __future__ import annotations

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
    parsed_command_input_matcher,
)
from ironsbot.services.bilibili.commands import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
    is_dynamic_update_text,
    parse_bili_push_mode_command,
)


def bilibili_command_contracts() -> tuple[CommandContract, ...]:
    """Describe all direct Bilibili dynamic commands."""

    return (
        *commands_from_rows(
            "bilibili",
            "查询",
            "bili_query",
            (
                (
                    "bilibili.dynamic",
                    DYNAMIC_MENU_COMMANDS[:1],
                    "查看订阅账号的最新动态",
                    {"show_in_poke": True},
                ),
                (
                    "bilibili.accounts",
                    BILI_ACCOUNT_COMMANDS[:1],
                    "查看当前会话订阅的账号",
                    {
                        "features_any": (),
                        "routing_aliases": BILI_ACCOUNT_COMMANDS,
                        "access": (
                            CommandAccess(features_any=("bili_query",)),
                            CommandAccess(
                                "group",
                                "group_manager",
                                ("bili_push",),
                            ),
                            CommandAccess("private", features_any=("bili_push",)),
                        ),
                    },
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "本群管理",
            "bili_push",
            (
                (
                    "bilibili.push_mode",
                    tuple(
                        f"{command} <账号> <内容|链接|默认>"
                        for command in BILI_PUSH_MODE_COMMANDS[:1]
                    ),
                    "调整当前会话指定账号的推送模式",
                    {
                        "access": (CommandAccess("group", "group_manager"),),
                        "routing_matcher": parsed_command_input_matcher(
                            parse_bili_push_mode_command
                        ),
                    },
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "私聊管理",
            "bili_push",
            (
                (
                    "bilibili.private_push_mode",
                    tuple(
                        f"{command} <账号> <内容|链接|默认>"
                        for command in BILI_PUSH_MODE_COMMANDS[:1]
                    ),
                    "调整当前私聊订阅账号的推送模式",
                    {
                        "access": (CommandAccess("private"),),
                        "routing_matcher": parsed_command_input_matcher(
                            parse_bili_push_mode_command
                        ),
                    },
                ),
            ),
        ),
        *commands_from_rows(
            "bilibili",
            "超级管理员",
            "bili_push",
            (
                (
                    "bilibili.refresh",
                    tuple(f"/{command}" for command in DYNAMIC_UPDATE_COMMANDS[:1]),
                    "立即刷新订阅动态",
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_matcher": lambda text, _context: (
                            is_dynamic_update_text(text)
                        ),
                    },
                ),
            ),
        ),
    )
