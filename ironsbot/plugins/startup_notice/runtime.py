# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from .config import get_startup_config
from .service import StartupNoticeProvider, StartupNoticeService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.shared.messaging import TargetSendSummary

startup_notice_service = StartupNoticeService()


async def _send_notice_part(
    *,
    message_text: str,
    subscription_key: str,
    action_name: str,
) -> TargetSendSummary:
    from ironsbot.shared.messaging import send_broadcast_message

    targets = startup_notice_service.get_targets()
    return await send_broadcast_message(
        Message(message_text),
        private_user_ids=targets.private_user_ids,
        group_ids=targets.group_ids,
        action_name=action_name,
        interval_seconds=1.2,
        subscription_key=subscription_key,
    )


async def send_startup_notice(
    _bot: Bot,
    providers: Sequence[StartupNoticeProvider],
) -> None:
    config = get_startup_config()
    if not startup_notice_service.should_send(config):
        return

    startup_notice_service.begin_send()

    try:
        targets = startup_notice_service.get_targets()
        if targets.is_empty:
            logger.warning("startup notice has no admin notice targets")
            return

        if config.delay > 0:
            await asyncio.sleep(config.delay)

        summaries: list[TargetSendSummary] = []
        summaries.append(
            await _send_notice_part(
                message_text=config.message,
                subscription_key="startup_notice",
                action_name="startup notice",
            )
        )

        summaries.extend(
            [
                await _send_notice_part(
                    message_text=message,
                    subscription_key=provider.subscription_key,
                    action_name=provider.action_name,
                )
                for provider in providers
                if (message := provider.get_message())
            ]
        )
        succeeded = [
            target
            for summary in summaries
            for target in summary.succeeded
        ]

        startup_notice_service.mark_result(succeeded)
        if startup_notice_service.state.sent:
            logger.info(
                "startup notice sent to {} targets in {} parts",
                len(set(succeeded)),
                len(summaries),
            )

    finally:
        startup_notice_service.finish_send()


__all__ = ["send_startup_notice"]
