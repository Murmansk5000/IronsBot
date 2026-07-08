# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_bots, get_driver, require
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.shared.scheduler import add_or_replace_job

from . import scan_team_resource_subscriptions
from .config import get_team_resource_config

_team_resource_runtime_state = {"registered": False}


async def _scan_team_resources_with_bot() -> None:
    bots = list(get_bots().values())
    if not bots:
        logger.warning("team resource scan skipped: no connected bot")
        return

    bot = bots[0]
    if not isinstance(bot, Bot):
        logger.warning("team resource scan skipped: first bot is not OneBot V11")
        return

    await scan_team_resource_subscriptions(bot)


def _register_team_resource_jobs(scheduler: Any) -> None:
    config = get_team_resource_config()
    if not config.enabled:
        return

    for time_text in config.times:
        hour_text, minute_text = time_text.split(":", maxsplit=1)
        add_or_replace_job(
            scheduler,
            _scan_team_resources_with_bot,
            "cron",
            hour=int(hour_text),
            minute=int(minute_text),
            job_id=f"team_resource_scan_{time_text.replace(':', '')}",
        )


def _setup_team_resource_runtime(driver: Any, scheduler: Any) -> None:
    if _team_resource_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_team_resource_jobs_on_startup() -> None:
        _register_team_resource_jobs(scheduler)

    _team_resource_runtime_state["registered"] = True


def setup_team_resource_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_team_resource_runtime(get_driver(), scheduler)


__all__ = ["setup_team_resource_runtime"]
