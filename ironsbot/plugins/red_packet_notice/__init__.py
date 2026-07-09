# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import on_message, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    NoticeEvent,
)
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config.loader import get_app_config
from ironsbot.services.red_packet_notice import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
    is_red_packet_message,
    is_red_packet_payload,
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


async def _is_red_packet_notice_payload(event: NoticeEvent) -> bool:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return False
    config = get_app_config().message.red_packet_notice
    return config.enabled and is_red_packet_payload(event.model_dump())


red_packet_notice_matcher = on_message(
    rule=Rule(_is_red_packet_notice_event),
    priority=get_matcher_priority("red_packet_notice", 1),
    block=False,
)
red_packet_notice_payload_matcher = on_notice(
    rule=Rule(_is_red_packet_notice_payload),
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
    await _send_red_packet_notice(
        bot=bot,
        group_id=event.group_id,
        sender_id=event.user_id,
        summary=summarize_red_packet_message(event.message),
    )


@red_packet_notice_payload_matcher.handle()
async def handle_red_packet_notice_payload(
    bot: Bot,
    event: NoticeEvent,
) -> None:
    await _send_red_packet_notice(
        bot=bot,
        group_id=int(getattr(event, "group_id", 0)),
        sender_id=int(getattr(event, "user_id", 0) or 0),
        summary="红包通知",
    )


async def _send_red_packet_notice(
    *,
    bot: Bot,
    group_id: int,
    sender_id: int,
    summary: str,
) -> None:
    if not _get_limiter().can_send(group_id):
        logger.info(f"red packet notice suppressed by cooldown for group {group_id}")
        return

    superuser_ids = sorted(get_superuser_ids())
    if not superuser_ids:
        logger.warning("red packet notice skipped: no superusers configured")
        return

    logger.info(f"red packet notice detected: group={group_id} sender={sender_id}")
    group_name = await _get_group_name(bot, group_id)
    notice = build_red_packet_notice_message(
        group_id=group_id,
        group_name=group_name,
        sender_id=sender_id,
        summary=summary,
    )
    await send_broadcast_message(
        notice,
        private_user_ids=superuser_ids,
        bot=bot,
        action_name="red packet notice",
        subscription_key=RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
    )
