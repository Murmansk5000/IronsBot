# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.core.messaging import FIXED_IMAGE_COMMANDS
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor
from ironsbot.runtime.feature_policy import event_is_feature_visible_in_help

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.features import FeatureService


def messaging_help_visible(
    event: Event,
    *,
    features: FeatureService,
    config: MessageConfig,
) -> bool:
    if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return False
    actions = [*config.commands, *config.schedules]
    return any(
        action.enabled
        and event_is_feature_visible_in_help(features, event, action.feature)
        for action in actions
    )


def configured_message_commands(
    config: MessageConfig,
) -> tuple[CommandDescriptor, ...]:
    configured = tuple(
        CommandDescriptor(
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
    schedules = tuple(
        CommandDescriptor(
            id=f"messaging.schedule.{action.id}",
            plugin_id="messaging",
            section="定时推送",
            examples=(
                _schedule_label(
                    action.name,
                    action.hour,
                    action.minute,
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
                    {
                        "show_in_poke": True,
                        "interaction": "conversation",
                    },
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


def _schedule_label(
    name: str,
    hour: int,
    minute: int,
    day_of_week: str | None,
) -> str:
    title = name or "定时推送"
    clock = f"{hour:02d}:{minute:02d}"
    timing = f"每天 {clock}" if day_of_week is None else f"每周 {day_of_week} {clock}"
    return f"{title}（{timing}）"


def configured_image_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    fixed = tuple(
        CommandDescriptor(
            id=f"sendpic.fixed.{command}",
            plugin_id="sendpic",
            section="固定图片",
            examples=(command,),
            description="发送固定图片",
            features_any=("image",),
            show_in_poke=True,
        )
        for command in FIXED_IMAGE_COMMANDS
    )
    configured = tuple(
        CommandDescriptor(
            id=f"sendpic.{item.id}",
            plugin_id="sendpic",
            section="自定义图片",
            examples=(item.command, *sorted(item.aliases)),
            description="发送配置的图片；可在命令后附加编号",
            features_any=("image",),
            show_in_poke=True,
        )
        for item in config.messaging.sendpic.configs
        if item.id in config.messaging.sendpic.enabled_ids
    )
    return (*fixed, *configured)


def ai_intent_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    if not config.ai.api_key.strip() or not config.ai.intent_actions_enabled:
        return ()
    return tuple(
        CommandDescriptor(
            id=f"ai_intent.{action_id}",
            plugin_id="ai_intent",
            section="关键词意图",
            examples=tuple(action.keywords),
            description="机器人识别到相应意图后自动回复",
            features_any=(action.feature,),
            interaction="automatic",
        )
        for action_id, action in config.ai.intent_actions.items()
        if action.enabled and action.keywords
    )
