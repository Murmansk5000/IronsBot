# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot import on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    Message,
    NoticeEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config import get_app_config
from ironsbot.shared.features import is_group_feature_allowed, resolve_group_refs
from ironsbot.shared.messaging.text import build_message, render_text

TEAM_AUDIT_WELCOME_PLUGIN_NAME = "team_audit_welcome"

__plugin_meta__ = PluginMetadata(
    name="战队审核入群提示",
    description="在指定战队审核群有新人入群时发送审核指引。",
    usage=(
        "配置 message.team_audit_welcome.enabled=true，并在 "
        "message.team_audit_welcome.groups 中填写群别名或群号。"
    ),
)


async def _is_group_increase(event: NoticeEvent) -> bool:
    return isinstance(event, GroupIncreaseNoticeEvent)


team_audit_welcome_matcher = on_notice(
    rule=Rule(_is_group_increase),
    priority=5,
    block=False,
)


def _target_groups() -> set[int]:
    config = get_app_config().message.team_audit_welcome
    return set(resolve_group_refs(config.groups))


def _welcome_message(user_id: int) -> Message:
    config = get_app_config().message.team_audit_welcome
    return build_message(render_text(config.message), at_user_ids=[user_id])


@team_audit_welcome_matcher.handle()
async def handle_team_audit_welcome(
    bot: Bot,
    event: GroupIncreaseNoticeEvent,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled:
        return

    if event.user_id == event.self_id:
        return

    if event.group_id not in _target_groups():
        return

    if not is_group_feature_allowed(event.user_id, event.group_id, config.feature):
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=_welcome_message(event.user_id),
    )
