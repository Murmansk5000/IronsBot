# SPDX-License-Identifier: MIT
"""Startup composition for the read-only host clock diagnostic."""

from __future__ import annotations

import logging
from statistics import median
from typing import TYPE_CHECKING

from ironsbot.integrations.http.clock import check_clock_drift

if TYPE_CHECKING:
    from ironsbot.config.models.settings import RuntimeSchedulerConfig
    from ironsbot.services.operations.startup import StartupNoticeService

logger = logging.getLogger(__name__)


async def check_configured_clock(
    config: RuntimeSchedulerConfig,
    startup_notice: StartupNoticeService,
) -> None:
    if not config.clock_check_on_startup:
        return

    samples = await check_clock_drift(
        timeout_seconds=config.clock_check_timeout_seconds,
    )
    if not samples:
        logger.warning("clock check unavailable: every HTTPS Date source failed")
        return

    offset_seconds = float(median(sample.offset_seconds for sample in samples))
    logger.info(
        "clock check complete: offset=%.3fs samples=%d timezone=%s",
        offset_seconds,
        len(samples),
        config.timezone,
    )
    if abs(offset_seconds) <= config.clock_warning_threshold_seconds:
        return

    direction = "slow" if offset_seconds > 0 else "fast"
    startup_notice.add(
        "startup_clock_check",
        "startup clock check",
        "Clock drift warning.\n"
        f"Estimated local clock: {abs(offset_seconds):.2f}s {direction}\n"
        f"Samples: {len(samples)}\n"
        "Check the Unraid host NTP configuration; IronsBot did not change system time.",
    )
    logger.warning(
        "clock drift exceeds threshold: offset=%.3fs threshold=%.3fs",
        offset_seconds,
        config.clock_warning_threshold_seconds,
    )
