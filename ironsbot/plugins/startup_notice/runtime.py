# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.shared.plugin_runtime.startup_ready import ensure_startup_ready

from .config import get_startup_config
from .service import StartupNoticeService

if TYPE_CHECKING:
    from ironsbot.shared.messaging import TargetSendSummary

startup_notice_service = StartupNoticeService()
_startup_notice_runtime_state = {"registered": False}


async def _send_notice_part(
    *,
    bot: Bot,
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
        bot=bot,
        action_name=action_name,
        interval_seconds=1.2,
        subscription_key=subscription_key,
    )


async def send_startup_notice(bot: Bot) -> None:
    from ironsbot.plugins.db_sync.runtime import get_startup_sync_notice
    from ironsbot.plugins.server_status.runtime import get_startup_docker_update_notice

    config = get_startup_config()
    if not startup_notice_service.should_send(config):
        return

    startup_notice_service.begin_send()

    try:
        targets = startup_notice_service.get_targets()
        if targets.is_empty:
            logger.warning("startup notice has no admin notice targets")
            return

        await ensure_startup_ready(bot)

        if config.delay > 0:
            await asyncio.sleep(config.delay)

        summaries: list[TargetSendSummary] = []
        summaries.append(
            await _send_notice_part(
                bot=bot,
                message_text=config.message,
                subscription_key="startup_notice",
                action_name="startup notice",
            )
        )

        startup_docker_update_notice = get_startup_docker_update_notice()
        if startup_docker_update_notice:
            summaries.append(
                await _send_notice_part(
                    bot=bot,
                    message_text=startup_docker_update_notice,
                    subscription_key="startup_docker_update",
                    action_name="startup docker update notice",
                )
            )

        startup_sync_notice = get_startup_sync_notice()
        if startup_sync_notice:
            summaries.append(
                await _send_notice_part(
                    bot=bot,
                    message_text=startup_sync_notice,
                    subscription_key="startup_data_sync",
                    action_name="startup data sync notice",
                )
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


def _setup_startup_notice_runtime(driver: Any) -> None:
    if _startup_notice_runtime_state["registered"]:
        return

    driver.on_bot_connect(send_startup_notice)
    _startup_notice_runtime_state["registered"] = True


def setup_startup_notice_runtime() -> None:
    _setup_startup_notice_runtime(get_driver())


__all__ = ["setup_startup_notice_runtime"]
