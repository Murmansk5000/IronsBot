# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    NoticeEvent,
)
from nonebot.log import logger
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.red_packet_notice import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
    is_red_packet_message,
    is_red_packet_payload,
    summarize_red_packet_message,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.admin_notice import send_admin_notice

RED_PACKET_NOTICE_SUBSCRIPTION_KEY = "red_packet_notice"

if TYPE_CHECKING:
    from ironsbot.config.models.message import RedPacketNoticeConfig


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


async def _send_red_packet_notice(
    *,
    bot: Bot,
    limiter: RedPacketNoticeLimiter,
    group_id: int,
    sender_id: int,
    summary: str,
) -> None:
    if not limiter.can_send(group_id):
        logger.info(f"red packet notice suppressed by cooldown for group {group_id}")
        return

    logger.info(f"red packet notice detected: group={group_id} sender={sender_id}")
    group_name = await _get_group_name(bot, group_id)
    notice = build_red_packet_notice_message(
        group_id=group_id,
        group_name=group_name,
        sender_id=sender_id,
        summary=summary,
    )
    await send_admin_notice(
        notice,
        action_name="red packet notice",
        subscription_key=RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
    )


def install(registry: MatcherRegistry, config: RedPacketNoticeConfig) -> None:
    limiter = RedPacketNoticeLimiter(config.cooldown_seconds)

    async def is_message(event: MessageEvent) -> bool:
        return (
            config.enabled
            and isinstance(event, GroupMessageEvent)
            and is_red_packet_message(event.message)
        )

    async def handle_message(bot: Bot, event: GroupMessageEvent) -> None:
        await _send_red_packet_notice(
            bot=bot,
            limiter=limiter,
            group_id=event.group_id,
            sender_id=event.user_id,
            summary=summarize_red_packet_message(event.message),
        )

    async def is_payload(event: NoticeEvent) -> bool:
        return (
            config.enabled
            and getattr(event, "group_id", None) is not None
            and is_red_packet_payload(event.model_dump())
        )

    async def handle_payload(bot: Bot, event: NoticeEvent) -> None:
        await _send_red_packet_notice(
            bot=bot,
            limiter=limiter,
            group_id=int(getattr(event, "group_id", 0)),
            sender_id=int(getattr(event, "user_id", 0) or 0),
            summary="红包通知",
        )

    message_matcher = registry.on_message(
        policy=CommandPolicy.exempt("passive red packet event detection"),
        rule=Rule(is_message),
        priority=get_matcher_priority("red_packet_notice", 1),
        block=False,
    )
    message_matcher.append_handler(handle_message)

    notice_matcher = registry.on_notice(
        rule=Rule(is_payload),
        priority=get_matcher_priority("red_packet_notice", 1),
        block=False,
    )
    notice_matcher.append_handler(handle_payload)
