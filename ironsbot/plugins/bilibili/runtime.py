# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot import get_driver, require
from nonebot.log import logger

from ironsbot.shared.plugin_runtime.startup_ready import register_startup_check

from .service import run_check_logic

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

_bilibili_monitor_runtime_state = {"registered": False}


async def auto_check_job() -> None:
    await run_check_logic()


async def register_bili_auto_check_job(scheduler: Any) -> None:
    scheduler.add_job(
        auto_check_job,
        "interval",
        minutes=1,
        id="bilibili_monitor_auto_check",
        replace_existing=True,
    )


async def _startup_check(bot: Bot) -> None:
    logger.info(f"Bilibili monitor saw bot connected: {bot.self_id}")
    await asyncio.sleep(2)
    await run_check_logic(is_startup_check=True)


def _setup_bilibili_monitor_runtime(driver: Any, scheduler: Any) -> None:
    if _bilibili_monitor_runtime_state["registered"]:
        return

    register_startup_check("bilibili_monitor", _startup_check)

    @driver.on_startup
    async def _register_bili_auto_check_on_startup() -> None:
        await register_bili_auto_check_job(scheduler)

    _bilibili_monitor_runtime_state["registered"] = True


def setup_bilibili_monitor_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_bilibili_monitor_runtime(get_driver(), scheduler)


__all__ = ["setup_bilibili_monitor_runtime"]
