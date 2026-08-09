# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.plugins.bilibili.command_rules import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
)

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings


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
                    "查看已订阅的账号",
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
            "群管理",
            "bili_push",
            (
                (
                    "bilibili.push_mode",
                    tuple(
                        f"{command} <账号> <内容|链接|默认>"
                        for command in BILI_PUSH_MODE_COMMANDS[:1]
                    ),
                    "调整指定账号的推送模式",
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
                    "调整订阅账号的推送模式",
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


def activity_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "activity",
            "查询",
            "seer_activity_query",
            (
                (
                    "activity.ending",
                    SOON_ENDING_ACTIVITY_COMMANDS[:1],
                    "查询即将结束的活动",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "activity",
            "超级管理员",
            "seer_activity_query",
            (
                (
                    "activity.current",
                    tuple(
                        f"/{command}" for command in CURRENT_ACTIVITY_COMMANDS[:1]
                    ),
                    "查询完整活动列表",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
            ),
        ),
    )


def team_resource_commands(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
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
                    "查看已订阅战队的信息和资源",
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
                    "取消指定战队订阅",
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
                    "查看和管理战队订阅",
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


def about_commands() -> tuple[CommandDescriptor, ...]:
    return commands_from_rows(
        "about",
        "查看",
        "about",
        (("about", ("关于",), "查看项目、版本和主要能力", {}),),
    )


def help_commands() -> tuple[CommandDescriptor, ...]:
    return commands_from_rows(
        "help",
        "查看",
        "help",
        (("help", ("帮助",), "查看当前会话可用功能", {"show_in_poke": True}),),
    )


def meeting_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    return commands_from_rows(
        "meeting",
        "查询",
        "meeting",
        (
            (
                "meeting",
                tuple(config.messaging.meeting.commands),
                "获取配置的腾讯会议信息",
                {"show_in_poke": True},
            ),
        ),
    )
