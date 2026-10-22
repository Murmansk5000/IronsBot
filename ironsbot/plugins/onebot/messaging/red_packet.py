# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    NoticeEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot import red_packet as packet_protocol
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.notice_events import (
    notice_context,
    notify_onebot_red_packet,
)

__plugin_meta__ = PluginMetadata(
    name="红包提醒",
    description="检测群红包并向管理通知目标发送提醒。",
    usage="由 messaging.red_packet_notice 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.services.messaging.red_packet import RedPacketNoticeService


def install(
    registry: MatcherFactory,
    service: RedPacketNoticeService,
) -> None:
    async def is_message(event: MessageEvent) -> bool:
        return isinstance(
            event, GroupMessageEvent
        ) and packet_protocol.is_red_packet_message(
            [{"type": part.type, "data": part.data} for part in event.message]
        )

    async def handle_message(bot: Bot, event: GroupMessageEvent) -> None:
        await service.handle(
            notice_context(event.user_id, event.group_id),
            summary=packet_protocol.summarize_red_packet_message(
                [{"type": part.type, "data": part.data} for part in event.message]
            ),
            conversation_name=partial(
                packet_protocol.red_packet_group_name, bot, event.group_id
            ),
        )

    async def is_payload(event: NoticeEvent) -> bool:
        return getattr(
            event, "group_id", None
        ) is not None and packet_protocol.is_red_packet_payload(event.model_dump())

    async def handle_payload(bot: Bot, event: NoticeEvent) -> None:
        group_id = int(getattr(event, "group_id", 0))
        await notify_onebot_red_packet(
            bot,
            int(getattr(event, "user_id", 0) or 0),
            group_id,
            service=service,
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
    service: RedPacketNoticeService,
) -> PluginContribution:
    """Declare passive red-packet detection and its admin delivery binding."""

    return PluginContribution(
        id="red_packet_notice",
        install=partial(install, service=service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.red_packet_notice,
        ),
    )
