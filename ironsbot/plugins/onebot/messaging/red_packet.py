# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    NoticeEvent,
)
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.services.messaging.red_packet import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
)

RED_PACKET_NOTICE_SUBSCRIPTION_KEY = "red_packet_notice"
RED_PACKET_SEGMENT_TYPES = frozenset(
    {"redbag", "redpacket", "red_packet", "hongbao", "lucky_money"}
)
RED_PACKET_EVENT_SUBTYPES = RED_PACKET_SEGMENT_TYPES
RED_PACKET_GRAY_TIP_BUSINESS_IDS = frozenset({"81"})
RED_PACKET_BUSINESS_ID_KEYS = frozenset(
    {"busi_id", "busiId", "business_id", "businessId"}
)
RED_PACKET_RAW_MARKERS = (
    "[CQ:redbag",
    "[CQ:redpacket",
    "[CQ:red_packet",
    "[CQ:hongbao",
    "[redbag:",
    "[redpacket:",
    "[red_packet:",
    "[hongbao:",
    "[QQ红包]",
    "QQ红包",
)
RED_PACKET_NOTICE_MARKERS = (*RED_PACKET_RAW_MARKERS, "红包")

__plugin_meta__ = PluginMetadata(
    name="红包提醒",
    description="检测群红包并向管理通知目标发送提醒。",
    usage="由 messaging.red_packet_notice 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import RedPacketNoticeConfig
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


def _payload_contains_marker(value: Any, markers: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in markers)
    if isinstance(value, Mapping):
        return any(_payload_contains_marker(item, markers) for item in value.values())
    if isinstance(value, Iterable):
        return any(_payload_contains_marker(item, markers) for item in value)
    return False


def _payload_has_red_packet_business_id(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(
            str(value.get(key) or "").strip() in RED_PACKET_GRAY_TIP_BUSINESS_IDS
            for key in RED_PACKET_BUSINESS_ID_KEYS
        ):
            return True
        return any(_payload_has_red_packet_business_id(item) for item in value.values())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return any(_payload_has_red_packet_business_id(item) for item in value)
    return False


def is_red_packet_message(message: Message) -> bool:
    for segment in message:
        if segment.type.lower() in RED_PACKET_SEGMENT_TYPES:
            return True
        if _payload_has_red_packet_business_id(segment.data):
            return True
        if _payload_contains_marker(segment.data, RED_PACKET_RAW_MARKERS):
            return True
    return _payload_has_red_packet_business_id(message) or _payload_contains_marker(
        str(message), RED_PACKET_RAW_MARKERS
    )


def is_red_packet_payload(payload: Mapping[str, Any]) -> bool:
    subtype = str(payload.get("sub_type") or "").strip().lower()
    return (
        subtype in RED_PACKET_EVENT_SUBTYPES
        or _payload_has_red_packet_business_id(payload)
        or _payload_contains_marker(payload, RED_PACKET_NOTICE_MARKERS)
    )


def summarize_red_packet_message(message: Message) -> str:
    for segment in message:
        if segment.type.lower() in RED_PACKET_SEGMENT_TYPES:
            title = str(segment.data.get("title") or "").strip()
            return title[:80] if title else "红包消息"

    plaintext = message.extract_plain_text().strip()
    return (plaintext or str(message).strip())[:80]


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


async def _send_red_packet_notice(  # noqa: PLR0913
    *,
    bot: Bot,
    limiter: RedPacketNoticeLimiter,
    group_id: int,
    sender_id: int,
    summary: str,
    admin_notices: AdminNoticeService,
) -> None:
    conversation = onebot_conversation_ref(group_id, group_id=group_id)
    sender = onebot_actor_ref(sender_id)
    if not limiter.can_send(conversation):
        logger.info(f"red packet notice suppressed by cooldown for group {group_id}")
        return

    logger.info(f"red packet notice detected: group={group_id} sender={sender_id}")
    group_name = await _get_group_name(bot, group_id)
    notice = build_red_packet_notice_message(
        conversation=conversation,
        conversation_name=group_name,
        sender=sender,
        summary=summary,
    )
    await admin_notices.send(
        notice,
        action_name="red packet notice",
        subscription_key=RED_PACKET_NOTICE_SUBSCRIPTION_KEY,
    )


def install(
    registry: MatcherFactory,
    config: RedPacketNoticeConfig,
    admin_notices: AdminNoticeService,
) -> None:
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
            admin_notices=admin_notices,
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
            admin_notices=admin_notices,
        )

    message_matcher = registry.on_message(
        policy=CommandPolicy.exempt("passive red packet event detection"),
        rule=Rule(is_message),
        priority=registry.priority("red_packet_notice"),
        block=False,
    )
    message_matcher.append_handler(handle_message)

    notice_matcher = registry.on_notice(
        rule=Rule(is_payload),
        priority=registry.priority("red_packet_notice"),
        block=False,
    )
    notice_matcher.append_handler(handle_payload)


def plugin_contribution(
    *,
    config: RedPacketNoticeConfig,
    admin_notices: AdminNoticeService,
) -> PluginContribution:
    """Declare passive red-packet detection and its admin delivery binding."""

    return PluginContribution(
        id="red_packet_notice",
        install=partial(
            install,
            config=config,
            admin_notices=admin_notices,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            config=context.settings.messaging.red_packet_notice,
            admin_notices=context.resources.admin_notices,
        ),
    )
