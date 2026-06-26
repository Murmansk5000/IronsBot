# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot import get_driver, require

from . import (
    register_team_audit_followup_scan,
    schedule_pending_team_audit_followups,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

_team_audit_welcome_runtime_state = {"registered": False}


def _setup_team_audit_welcome_runtime(driver: Any, scheduler: Any) -> None:
    if _team_audit_welcome_runtime_state["registered"]:
        return

    @driver.on_bot_connect
    async def _schedule_team_audit_followups_on_connect(bot: Bot) -> None:
        await schedule_pending_team_audit_followups(bot, scheduler)
        register_team_audit_followup_scan(scheduler, bot)

    _team_audit_welcome_runtime_state["registered"] = True


def setup_team_audit_welcome_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_team_audit_welcome_runtime(get_driver(), scheduler)


__all__ = ["setup_team_audit_welcome_runtime"]
