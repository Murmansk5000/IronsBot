# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot.adapters.onebot.v11 import Bot  # noqa: TC002

from .followup import (
    register_team_audit_followup_scan,
    schedule_pending_team_audit_followups,
)


async def schedule_team_audit_followups_on_connect(
    bot: Bot,
    *,
    scheduler: Any,
) -> None:
    del bot
    await schedule_pending_team_audit_followups(scheduler)
    register_team_audit_followup_scan(scheduler)


__all__ = ["schedule_team_audit_followups_on_connect"]
