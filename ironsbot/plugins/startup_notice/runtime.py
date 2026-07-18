# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import StartupConfig
    from ironsbot.services.startup_notice import StartupNoticeService
    from ironsbot.shared.messaging import AdminNoticeTargets, TargetSendSummary


async def _send_notice_part(
    *,
    message_text: str,
    subscription_key: str,
    action_name: str,
    targets: AdminNoticeTargets,
) -> TargetSendSummary:
    from ironsbot.shared.messaging import send_broadcast_message

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
    service: StartupNoticeService,
    config: StartupConfig,
) -> None:
    if not service.should_send(enabled=config.enabled):
        return

    service.begin_send()

    try:
        targets = service.get_targets()
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
                targets=targets,
            )
        )

        summaries.extend(
            [
                await _send_notice_part(
                    message_text=part.message,
                    subscription_key=part.subscription_key,
                    action_name=part.action_name,
                    targets=targets,
                )
                for part in service.parts
            ]
        )
        succeeded = [target for summary in summaries for target in summary.succeeded]

        service.mark_result(succeeded)
        if service.sent:
            logger.info(
                "startup notice sent to {} targets in {} parts",
                len(set(succeeded)),
                len(summaries),
            )

    finally:
        service.finish_send()


__all__ = ["send_startup_notice"]
