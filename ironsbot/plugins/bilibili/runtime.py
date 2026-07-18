# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Any

from nonebot.log import logger

from ironsbot.integrations.scheduler.jobs import JobRegistry

from .service import run_check_logic

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.shared.messaging.admin_notice import AdminNoticeService

BILIBILI_MONITOR_JOB_PREFIX = "bilibili_monitor_"


async def register_bili_auto_check_job(
    scheduler: Any,
    admin_notices: AdminNoticeService,
) -> None:
    JobRegistry(scheduler, prefix=BILIBILI_MONITOR_JOB_PREFIX).add(
        partial(run_check_logic, admin_notices),
        "interval",
        minutes=1,
        job_id="auto_check",
    )


async def check_bilibili_on_connect(
    bot: Bot,
    admin_notices: AdminNoticeService,
) -> None:
    logger.info(f"Bilibili monitor saw bot connected: {bot.self_id}")
    await asyncio.sleep(2)
    await run_check_logic(admin_notices, is_startup_check=True)
