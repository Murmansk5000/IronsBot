# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for configured text messaging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
)

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import MessageConfig


def messaging_command_contracts(
    config: MessageConfig,
) -> tuple[CommandContract, ...]:
    """Describe configured messaging commands for the shared command catalog."""

    configured = tuple(
        CommandContract(
            id=f"messaging.{action.id}",
            plugin_id="messaging",
            section="配置口令",
            examples=tuple(action.commands),
            description=action.name or "发送配置的文本或链接",
            features_any=(action.feature,),
            show_in_poke=True,
        )
        for action in config.commands
        if action.enabled
    )
    keyword_replies = tuple(
        CommandContract(
            id=f"messaging.keyword.{action.id}",
            plugin_id="messaging",
            section="关键词回复",
            examples=tuple(action.keywords),
            description=action.name or "消息包含关键词时自动回复",
            features_any=(action.feature,),
            interaction="automatic",
        )
        for action in config.keyword_replies
        if action.enabled
    )
    schedules = tuple(
        CommandContract(
            id=f"messaging.schedule.{action.id}",
            plugin_id="messaging",
            section="定时推送",
            examples=(
                scheduled_message_command_label(
                    action.name,
                    action.time,
                    action.day_of_week,
                ),
            ),
            description="按配置时间自动发送推送内容",
            features_any=(action.feature,),
            interaction="automatic",
        )
        for action in config.schedules
        if action.enabled
    )
    subscription_commands = tuple(
        dict.fromkeys(
            (
                "推送管理",
                *config.push_unsubscribe.commands,
                *config.push_unsubscribe.restore_commands,
            )
        )
    )
    return (
        *configured,
        *keyword_replies,
        *schedules,
        *commands_from_rows(
            "messaging",
            "推送管理",
            None,
            (
                (
                    "messaging.push_subscription",
                    subscription_commands,
                    "查看当前会话的推送订阅；群主和管理员可切换本群订阅",
                    {"show_in_poke": True, "interaction": "conversation"},
                ),
            ),
        ),
        *commands_from_rows(
            "messaging",
            "本群管理",
            None,
            (
                (
                    "messaging.push_time",
                    ("推送时间", "提醒时间"),
                    "管理本群定时推送和活动提醒时间",
                    {
                        "access": (CommandAccess("group", "group_manager"),),
                        "show_in_poke": True,
                        "interaction": "conversation",
                    },
                ),
            ),
        ),
    )


def scheduled_message_command_label(
    name: str,
    time: str,
    day_of_week: str | None,
) -> str:
    """Format a configured schedule as a help-only automatic action label."""

    title = name or "定时推送"
    timing = f"每天 {time}" if day_of_week is None else f"每周 {day_of_week} {time}"
    return f"{title}（{timing}）"
