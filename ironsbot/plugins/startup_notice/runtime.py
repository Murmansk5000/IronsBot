# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import Any

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.shared.plugin_runtime.startup_ready import ensure_startup_ready

from .config import get_startup_config
from .service import StartupNoticeService

startup_notice_service = StartupNoticeService()
_startup_notice_runtime_state = {"registered": False}


async def send_startup_notice(bot: Bot) -> None:
    from ironsbot.shared.messaging import send_broadcast_message

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

        summary = await send_broadcast_message(
            Message(config.message),
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            bot=bot,
            action_name="startup notice",
            interval_seconds=1.2,
            subscription_key="admin_notice",
        )

        startup_notice_service.mark_result(summary.succeeded)
        if startup_notice_service.state.sent:
            logger.info(f"startup notice sent to {len(summary.succeeded)} users")

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
