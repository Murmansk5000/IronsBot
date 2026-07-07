# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config import get_app_config
from ironsbot.services.red_packet_notice import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
    is_red_packet_message,
    summarize_red_packet_message,
)
from ironsbot.shared.features import get_superuser_ids
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.senders import send_broadcast_message

RED_PACKET_NOTICE_SUBSCRIPTION_KEY = "red_packet_notice"

__plugin_meta__ = PluginMetadata(
    name="红包提醒",
    description="检测群红包消息并私聊通知超级管理员。",
    usage="检测到群红包时私聊超级管理员，消息包含群号、群名和发送者；不会领取红包。",
)

_limiter: RedPacketNoticeLimiter | None = None


def _get_limiter() -> RedPacketNoticeLimiter:
    global _limiter  # noqa: PLW0603

    cooldown_seconds = get_app_config().message.red_packet_notice.cooldown_seconds
    if _limiter is None or _limiter.cooldown_seconds != cooldown_seconds:
        _limiter = RedPacketNoticeLimiter(cooldown_seconds=cooldown_seconds)
    return _limiter


async def _is_red_packet_notice_event(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    config = get_app_config().message.red_packet_notice
    return config.enabled and is_red_packet_message(event.message)


red_packet_notice_matcher = on_message(
    rule=Rule(_is_red_packet_notice_event),
    priority=get_matcher_priority("red_packet_notice", 1),
    block=False,
)


async def _get_group_name(bot: Bot, group_id: int) -> str:
    try:
        info: dict[str, Any] = await bot.get_group_info(
            group_id=group_id,
            no_cache=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"red packet notice failed to get group info: {e}")
        return ""

    return str(info.get("group_name") or "").strip()


@red_packet_notice_matcher.handle()
async def handle_red_packet_notice(
    bot: Bot,
    event: GroupMessageEvent,
) -> None:
    if not _get_limiter().can_send(event.group_id):
        logger.info(
            f"red packet notice suppressed by cooldown for group {event.group_id}"
        )
        return

    superuser_ids = sorted(get_superuser_ids())
    if not superuser_ids:
        logger.warning("red packet notice skipped: no superusers configured")
        return

    group_name = await _get_group_name(bot, event.group_id)
    notice = build_red_packet_notice_message(
        group_id=event.group_id,
        group_name=group_name,
        sender_id=event.user_id,
        summary=summarize_red_packet_message(event.message),
    )
    await send_broadcast_message(
        notice,
        private_user_ids=superuser_ids,
        bot=bot,
        action_name="red packet notice",
        subscription_key=RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
    )
