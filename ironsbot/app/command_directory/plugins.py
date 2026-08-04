# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.plugins.bilibili.command_rules import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor


def bilibili_commands() -> tuple[CommandDescriptor, ...]:
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
                    {"access": (CommandAccess("group", "group_manager"),)},
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
                    {"access": (CommandAccess("private"),)},
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
                    tuple(
                        f"/{command}" for command in DYNAMIC_UPDATE_COMMANDS[:1]
                    ),
                    "立即刷新订阅动态",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
            ),
        ),
    )
def ai_chat_commands(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "ai_chat",
            "群聊",
            "ai_chat",
            (
                (
                    "ai_chat.group",
                    ("@机器人 <问题>",),
                    "向 AI 聊天提问",
                    {"access": (CommandAccess(scope="group"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "ai_chat",
            "私聊",
            "ai_chat",
            (
                (
                    "ai_chat.private",
                    ("<问题>",),
                    "直接向 AI 聊天提问",
                    {"access": (CommandAccess(scope="private"),)},
                ),
            ),
        ),
    )
