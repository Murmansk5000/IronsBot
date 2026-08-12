# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.bilibili.monitor import run_monitor_check
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.services.bilibili.monitor import (
        AuthInvalidHandler,
        DynamicPushSender,
    )
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)
BILIBILI_MONITOR_JOB_PREFIX = "bilibili_monitor_"
DEFAULT_REGULAR_CHECK_SECOND = 5


@dataclass(frozen=True, slots=True)
class BilibiliMonitorService:
    service: BilibiliService
    _on_auth_invalid: AuthInvalidHandler
    _send_push: DynamicPushSender
    check_second: int = DEFAULT_REGULAR_CHECK_SECOND

    async def notify_auth_invalid(self, reason: str) -> None:
        await self._on_auth_invalid(reason)

    async def check(
        self,
        *,
        is_startup_check: bool = False,
        force: bool = False,
    ) -> bool:
        return await run_monitor_check(
            self.service,
            on_auth_invalid=self._on_auth_invalid,
            send_push=self._send_push,
            is_startup_check=is_startup_check,
            force=force,
        )

    async def register_job(self, scheduler: Scheduler) -> None:
        jobs = JobRegistry(scheduler, prefix=BILIBILI_MONITOR_JOB_PREFIX)
        jobs.add(
            self.check,
            "cron",
            minute="*",
            second=self.check_second,
            job_id="auto_check",
        )

    async def check_on_connect(self, bot_id: str) -> None:
        logger.info("Bilibili monitor saw bot connected: %s", bot_id)
        await asyncio.sleep(2)
        await self.check(is_startup_check=True)
        self.service.spawn(
            self.service.backfill_recent_empty_bodies(),
            name="bilibili-history-backfill",
        )
