# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.bilibili.monitor import run_monitor_check
from ironsbot.services.bilibili.schedule import boost_schedule_entries
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.bilibili.monitor import (
        AuthInvalidHandler,
        DynamicPushSender,
        MonitorCheckResult,
    )
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)
BILIBILI_MONITOR_JOB_PREFIX = "bilibili_monitor_"
BILIBILI_REFRESH_COMPLETED = "✅ 动态刷新完成。"
BILIBILI_REFRESH_BUSY = "⏳ 动态刷新正在进行中，请稍后再试。"
BILIBILI_REFRESH_FAILED = "❌ 动态刷新失败。"


@dataclass(frozen=True, slots=True)
class BilibiliMonitorService:
    service: BilibiliService
    _on_auth_invalid: AuthInvalidHandler
    _send_push: DynamicPushSender
    check_second: int | None = None
    startup_recovery: Callable[[str], Awaitable[None]] | None = None

    async def notify_auth_invalid(self, reason: str) -> None:
        await self._on_auth_invalid(reason)

    async def manual_refresh(self) -> str:
        """Force one check and classify its observable result for any adapter."""

        result = await self.check(is_startup_check=True, force=True)
        if not result.executed:
            return BILIBILI_REFRESH_BUSY
        if not result.valid_response:
            return BILIBILI_REFRESH_FAILED
        return BILIBILI_REFRESH_COMPLETED

    async def check(
        self,
        *,
        is_startup_check: bool = False,
        force: bool = False,
    ) -> MonitorCheckResult:
        return await run_monitor_check(
            self.service,
            on_auth_invalid=self._on_auth_invalid,
            send_push=self._send_push,
            is_startup_check=is_startup_check,
            force=force,
        )

    async def register_job(self, scheduler: Scheduler) -> None:
        jobs = JobRegistry(scheduler, prefix=BILIBILI_MONITOR_JOB_PREFIX)
        check_second = (
            self.service.config.polling.check_second
            if self.check_second is None
            else self.check_second
        )
        jobs.add(
            self.check,
            "cron",
            minute="*",
            second=check_second,
            job_id="auto_check",
        )
        for entry in boost_schedule_entries(self.service.config.polling):
            if entry.second == check_second:
                continue
            jobs.add(
                self.check,
                "cron",
                hour=entry.hour,
                minute=entry.minute,
                second=entry.second,
                job_id=entry.job_suffix,
            )

    async def check_on_connect(self, bot_id: str) -> None:
        logger.info("Bilibili monitor saw bot connected: %s", bot_id)
        await asyncio.sleep(2)
        if self.startup_recovery is not None:
            await self.startup_recovery(bot_id)
        await self.check(is_startup_check=True)
