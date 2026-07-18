# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from nonebot import get_driver, require
from nonebot.log import logger

from ironsbot.core.commands import positive_int_list
from ironsbot.services.activity.config import get_activity_config
from ironsbot.services.activity.delivery import (
    activity_reminder_targets,
    build_reminder_delivery,
)
from ironsbot.services.activity.runtime_keys import ACTIVITY_REMINDER_REFRESH_KEY
from ironsbot.services.activity.scheduler import (
    register_scan_jobs,
    replace_reminder_jobs,
)
from ironsbot.services.activity.seer_activity import (
    scheduled_reminders,
    valid_reminders_before_send,
)
from ironsbot.services.activity.sent_cache import filter_unsent, mark_sent
from ironsbot.shared.messaging.push_subscription_models import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)
from ironsbot.shared.promotions import append_fire_manual_ad_for_group
from ironsbot.shared.runtime.refresh import register_runtime_refresh

from . import _now, _seer_activity_source

if TYPE_CHECKING:
    from ironsbot.services.activity.models import ActivityReminder

REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)
ACTIVITY_PUSH_SUBSCRIPTION_KEY = "seer_activity_push"

_activity_reminder_runtime_state: dict[str, Any] = {
    "registered": False,
    "scheduler": None,
}


async def send_activity_reminder(
    *,
    lead_hours: int,
    reminders: list[ActivityReminder],
) -> None:
    from ironsbot.shared.messaging import send_broadcast_message

    now = _now()
    reminders = valid_reminders_before_send(
        _seer_activity_source,
        reminders,
        now=now,
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
        _activity_reminder_targets_for_lead(lead_hours),
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
        message_limiter=append_fire_manual_ad_for_group,
        subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
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
                _seer_activity_source,
                _now(),
                lead_hours=_configured_activity_lead_hours(config.lead_hours),
                grace=timedelta(minutes=config.grace_minutes),
            )
        )
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("activity reminder scan failed")
        return

    if not reminders:
        logger.info("activity reminder scan found no pending reminders")
        return

    scheduled_count = replace_reminder_jobs(
        scheduler,
        send_activity_reminder,
        reminders,
        grace_minutes=config.grace_minutes,
    )

    logger.info(f"activity reminder scheduled {scheduled_count} pending reminders")


def _activity_push_store() -> PushUnsubscribeStore:
    from ironsbot.config.loader import get_app_config

    return PushUnsubscribeStore(get_app_config().message.push_unsubscribe.data_path)


def _configured_activity_lead_hours(default_lead_hours: list[int]) -> list[int]:
    lead_hours = set(default_lead_hours)
    store = _activity_push_store()
    for preference in store.all_time_preferences(
        subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
    ):
        lead_hours.update(positive_int_list(preference.value))
    return sorted(lead_hours, reverse=True)


def _effective_activity_lead_hours(
    target_type: str,
    target_id: int,
    default_lead_hours: list[int],
) -> list[int]:
    preference = _activity_push_store().get_time_preference(
        target_type,  # type: ignore[arg-type]
        target_id,
        ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
    )
    if preference is None:
        return default_lead_hours
    lead_hours = positive_int_list(preference)
    return lead_hours or default_lead_hours


def _activity_reminder_targets_for_lead(lead_hours: int):
    default_lead_hours = get_activity_config().lead_hours
    targets = activity_reminder_targets()
    group_ids = tuple(
        group_id
        for group_id in targets.group_ids
        if lead_hours
        in _effective_activity_lead_hours("group", group_id, default_lead_hours)
    )
    private_user_ids = tuple(
        user_id
        for user_id in targets.private_user_ids
        if lead_hours
        in _effective_activity_lead_hours("private", user_id, default_lead_hours)
    )
    return type(targets)(group_ids=group_ids, private_user_ids=private_user_ids)


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
    register_runtime_refresh(ACTIVITY_REMINDER_REFRESH_KEY, schedule_activity_reminders)

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
