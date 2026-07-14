from typing import Any

from nonebot import get_driver, require

from ironsbot.services.activity.runtime_keys import ACTIVITY_REMINDER_REFRESH_KEY
from ironsbot.shared.messaging.push_subscription_models import (
    CRON_TIME_PREFERENCE,
)
from ironsbot.shared.runtime.refresh import refresh_runtime

from . import schedules as message_schedules
from .push_time import (
    PushTimeOption,
)

_messaging_runtime_state = {"registered": False, "scheduler": None}


async def refresh_push_time_jobs(option: PushTimeOption) -> None:
    if option.preference_type == CRON_TIME_PREFERENCE:
        await refresh_message_schedules()
        return

    await refresh_runtime(ACTIVITY_REMINDER_REFRESH_KEY)


async def register_message_schedules(scheduler: Any) -> None:
    await message_schedules.register_message_schedules(scheduler)


async def refresh_message_schedules() -> None:
    scheduler = _messaging_runtime_state.get("scheduler")
    if scheduler is None:
        return
    await register_message_schedules(scheduler)


def _setup_messaging_runtime(driver: Any, scheduler: Any) -> None:
    if _messaging_runtime_state["registered"]:
        _messaging_runtime_state["scheduler"] = scheduler
        return

    _messaging_runtime_state["scheduler"] = scheduler

    @driver.on_startup
    async def _register_message_schedules_on_startup() -> None:
        await register_message_schedules(scheduler)

    _messaging_runtime_state["registered"] = True


def setup_messaging_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_messaging_runtime(get_driver(), scheduler)
