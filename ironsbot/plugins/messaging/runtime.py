from typing import Any

from nonebot import get_driver, on_message, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.push_subscriptions import (
    CRON_TIME_PREFERENCE,
)
from ironsbot.utils.rule import no_reply

from . import schedules as message_schedules
from .command_handlers import (
    dispatch_group_command,
    dispatch_private_command,
    register_messaging_plugin,
)
from .matcher_rules import (
    match_group_command,
    match_private_command,
    match_push_subscription_command,
    match_push_time_command,
)
from .push_management_handlers import register_push_management_handlers
from .push_time import (
    PushTimeOption,
)

_messaging_runtime_state = {"registered": False, "scheduler": None}


def _message_subscription_priority() -> int:
    return max(get_matcher_priority("message_commands", 4) - 1, 0)


private_command_matcher = on_message(
    rule=Rule(match_private_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)

push_subscription_matcher = on_message(
    rule=Rule(match_push_subscription_command) & no_reply(),
    priority=_message_subscription_priority(),
    block=True,
)

push_time_matcher = on_message(
    rule=Rule(match_push_time_command) & no_reply(),
    priority=_message_subscription_priority(),
    block=True,
)

group_command_matcher = on_message(
    rule=Rule(match_group_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)


register_messaging_plugin(
    private_matcher=private_command_matcher,
    group_matcher=group_command_matcher,
)


@private_command_matcher.handle()
async def handle_private_command(
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    await dispatch_private_command(
        private_matcher=private_command_matcher,
        event=event,
        state=state,
    )


async def _refresh_push_time_jobs(option: PushTimeOption) -> None:
    if option.preference_type == CRON_TIME_PREFERENCE:
        await refresh_message_schedules()
        return

    from ironsbot.plugins.activity.runtime import schedule_activity_reminders

    await schedule_activity_reminders()


register_push_management_handlers(
    push_subscription_matcher=push_subscription_matcher,
    push_time_matcher=push_time_matcher,
    refresh_push_time_jobs=_refresh_push_time_jobs,
)


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_group_command(
        group_matcher=group_command_matcher,
        event=event,
        state=state,
    )


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
