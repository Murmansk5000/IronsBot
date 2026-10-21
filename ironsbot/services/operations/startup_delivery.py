# SPDX-License-Identifier: MIT
"""Shared startup notification delivery for all transports."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.config.models.operations import StartupConfig
    from ironsbot.services.messaging.admin_notice import AdminNoticeSendSummary
    from ironsbot.services.operations.startup import StartupNoticeService

logger = logging.getLogger(__name__)


async def _send_notice_part(
    *,
    service: StartupNoticeService,
    message_text: str,
    subscription_key: str,
    action_name: str,
) -> AdminNoticeSendSummary:
    return await service.admin_notices.send(
        message_text,
        action_name=action_name,
        subscription_key=subscription_key,
    )


async def send_startup_notice(
    service: StartupNoticeService,
    config: StartupConfig,
) -> None:
    await service.flush_pending()
    if not service.should_send(enabled=config.enabled):
        return

    service.begin_send()

    try:
        targets = service.admin_notices.targets()
        if targets.is_empty:
            logger.warning("startup notice has no admin notice targets")
            return

        if config.delay > 0:
            await asyncio.sleep(config.delay)

        summaries: list[AdminNoticeSendSummary] = []
        summaries.append(
            await _send_notice_part(
                message_text=config.message,
                service=service,
                subscription_key="startup_notice",
                action_name="startup notice",
            )
        )
        summaries.extend(
            [
                await _send_notice_part(
                    message_text=part.message,
                    service=service,
                    subscription_key=part.subscription_key,
                    action_name=part.action_name,
                )
                for part in service.parts
            ]
        )
        succeeded = [target for summary in summaries for target in summary.succeeded]

        service.mark_result(succeeded)
        if service.sent:
            logger.info(
                "startup notice sent to %s targets in %s parts",
                len(set(succeeded)),
                len(summaries),
            )
    finally:
        service.finish_send()
