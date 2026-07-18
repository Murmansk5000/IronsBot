# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot.log import logger

from ironsbot.shared.runtime.jobs import JobRegistry

from .service import run_check_logic

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

BILIBILI_MONITOR_JOB_PREFIX = "bilibili_monitor_"


async def auto_check_job() -> None:
    await run_check_logic()


async def register_bili_auto_check_job(scheduler: Any) -> None:
    JobRegistry(scheduler, prefix=BILIBILI_MONITOR_JOB_PREFIX).add(
        auto_check_job,
        "interval",
        minutes=1,
        job_id="auto_check",
    )


async def check_bilibili_on_connect(bot: Bot) -> None:
    logger.info(f"Bilibili monitor saw bot connected: {bot.self_id}")
    await asyncio.sleep(2)
    await run_check_logic(is_startup_check=True)


__all__ = [
    "check_bilibili_on_connect",
    "register_bili_auto_check_job",
]
