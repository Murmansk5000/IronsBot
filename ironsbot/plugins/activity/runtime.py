# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from nonebot import get_driver, require
from nonebot.log import logger

from ironsbot.services.activity.delivery import (
    activity_reminder_targets,
    build_reminder_delivery,
)
from ironsbot.services.activity.query import (
    scheduled_reminders,
    valid_reminders_before_send,
)
from ironsbot.services.activity.scheduler import (
    register_scan_jobs,
    schedule_reminder_jobs,
)
from ironsbot.services.activity.sent_cache import filter_unsent, mark_sent

from . import _activity_query_source, _now
from .config import get_activity_config

if TYPE_CHECKING:
    from ironsbot.services.activity.models import ActivityReminder

REMINDER_SEND_DELAY = timedelta(minutes=10)
REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)

_activity_reminder_runtime_state: dict[str, Any] = {
    "registered": False,
    "scheduler": None,
}


async def send_activity_reminder(
    *,
    lead_hours: int,
    reminders: list[ActivityReminder],
) -> None:
    from ironsbot.plugins.messaging import send_broadcast_message

    reminders = valid_reminders_before_send(
        _activity_query_source,
        reminders,
        now=_now(),
        dispatch_tolerance=REMINDER_DISPATCH_TOLERANCE,
    )
    if not reminders:
        logger.info(
            f"activity ending reminder {lead_hours}h skipped: no valid reminders"
        )
        return

    delivery = build_reminder_delivery(
        lead_hours,
        reminders,
        activity_reminder_targets(),
        template=get_activity_config().message,
    )
    if delivery.status == "skip_no_targets":
        logger.warning("activity reminder skipped: no target groups or users")
        return

    summary = await send_broadcast_message(
        delivery.message,
        group_ids=delivery.group_ids,
        private_user_ids=delivery.private_user_ids,
        action_name=delivery.action_name,
        interval_seconds=1.2,
    )
    if summary.succeeded:
        mark_sent(reminders)


async def schedule_activity_reminders() -> None:
    scheduler = _activity_reminder_runtime_state["scheduler"]
    if scheduler is None:
        logger.warning("activity reminder scheduler is not configured")
        return

    config = get_activity_config()
    if not config.enabled:
        return

    try:
        reminders = filter_unsent(
            scheduled_reminders(
                _activity_query_source,
                _now(),
                lead_hours=config.lead_hours,
                reminder_send_delay=REMINDER_SEND_DELAY,
                grace=timedelta(minutes=config.grace_minutes),
            )
        )
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("activity reminder scan failed")
        return

    if not reminders:
        logger.info("activity reminder scan found no pending reminders")
        return

    scheduled_count = schedule_reminder_jobs(
        scheduler,
        send_activity_reminder,
        reminders,
        grace_minutes=config.grace_minutes,
    )

    logger.info(f"activity reminder scheduled {scheduled_count} pending reminders")


def register_activity_reminder_jobs(scheduler: Any) -> None:
    register_scan_jobs(
        scheduler,
        schedule_activity_reminders,
        enabled=get_activity_config().enabled,
        now=_now(),
    )


def _setup_activity_reminder_runtime(driver: Any, scheduler: Any) -> None:
    if _activity_reminder_runtime_state["registered"]:
        return

    _activity_reminder_runtime_state["scheduler"] = scheduler

    @driver.on_startup
    async def _register_activity_reminder_jobs_on_startup() -> None:
        register_activity_reminder_jobs(scheduler)

    _activity_reminder_runtime_state["registered"] = True


def setup_activity_reminder_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_activity_reminder_runtime(get_driver(), scheduler)


__all__ = [
    "register_activity_reminder_jobs",
    "schedule_activity_reminders",
    "send_activity_reminder",
    "setup_activity_reminder_runtime",
]
