from typing import Any

from nonebot import get_driver, on_message, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.plugins.fire_manual_ad.service import (
    append_fire_manual_ad_for_group,
    append_fire_manual_ad_text,
)
from ironsbot.shared.features import (
    groups_for_feature,
    is_group_feature_allowed,
    is_private_feature_allowed,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    event_sender_at_user_ids,
    finish_matcher_message,
    send_broadcast_message,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import (
    GroupScheduledMessageAction,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    get_message_config,
)
from .runtime_service import (
    build_schedule_job_id,
    build_schedule_trigger_kwargs,
    find_command_action,
)

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"
MESSAGE_PLUGIN_NAME = "message"
_messaging_runtime_state = {"registered": False}


def _private_action_allowed(
    event: PrivateMessageEvent,
    action: PrivateCommandMessageAction,
) -> bool:
    return is_private_feature_allowed(
        event.user_id,
        action.feature,
    )


async def _match_private_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.private_commands,
        is_allowed=lambda candidate: _private_action_allowed(event, candidate),
    )
    if action is not None:
        state[PRIVATE_ACTION_KEY] = action
        return True

    return False


async def _match_group_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.group_commands,
        is_allowed=lambda candidate: is_group_feature_allowed(
            event.user_id,
            event.group_id,
            candidate.feature,
        ),
    )
    if action is not None:
        state[GROUP_ACTION_KEY] = action
        return True

    return False


private_command_matcher = on_message(
    rule=Rule(_match_private_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)

group_command_matcher = on_message(
    rule=Rule(_match_group_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)


class MessagingPlugin:
    name = MESSAGE_PLUGIN_NAME
    feature = "text"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "private_command" and isinstance(
            event,
            PrivateMessageEvent,
        ):
            await self._handle_private_command(event, context)
            return

        if context.action == "group_command" and isinstance(event, GroupMessageEvent):
            await self._handle_group_command(event, context)
            return

    async def _handle_private_command(
        self,
        event: PrivateMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[PRIVATE_ACTION_KEY]
        await finish_matcher_message(
            context.matcher or private_command_matcher,
            action.message,
            event=event,
        )

    async def _handle_group_command(
        self,
        event: GroupMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[GROUP_ACTION_KEY]
        at_user_ids = [
            *event_sender_at_user_ids(event),
            *action.at_user_ids,
        ]
        await finish_matcher_message(
            context.matcher or group_command_matcher,
            action.message,
            at_user_ids=at_user_ids,
            event=event,
        )


register_plugin(MessagingPlugin())


@private_command_matcher.handle()
async def handle_private_command(
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=private_command_matcher,
        state=state,
        action="private_command",
    )


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=group_command_matcher,
        state=state,
        action="group_command",
    )


async def _send_private_schedule(task: PrivateScheduledMessageAction) -> None:
    await send_broadcast_message(
        append_fire_manual_ad_text(task.message),
        private_user_ids=users_with_superusers(users_for_feature(task.feature)),
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
    )


async def _send_group_schedule(task: GroupScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        group_ids=groups_for_feature(task.feature),
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=append_fire_manual_ad_for_group,
    )


def _register_private_schedule(
    scheduler: Any,
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    scheduler.add_job(
        _send_private_schedule,
        "cron",
        kwargs={"task": task},
        id=build_schedule_job_id("private_schedule", index, task.id),
        replace_existing=True,
        **build_schedule_trigger_kwargs(task),
    )


def _register_group_schedule(
    scheduler: Any,
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    scheduler.add_job(
        _send_group_schedule,
        "cron",
        kwargs={"task": task},
        id=build_schedule_job_id("group_schedule", index, task.id),
        replace_existing=True,
        **build_schedule_trigger_kwargs(task),
    )


async def register_message_schedules(scheduler: Any) -> None:
    config = get_message_config()
    for index, task in enumerate(config.private_schedules, start=1):
        _register_private_schedule(scheduler, index, task)

    for index, task in enumerate(config.group_schedules, start=1):
        _register_group_schedule(scheduler, index, task)


def _setup_messaging_runtime(driver: Any, scheduler: Any) -> None:
    if _messaging_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_message_schedules_on_startup() -> None:
        await register_message_schedules(scheduler)

    _messaging_runtime_state["registered"] = True


def setup_messaging_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_messaging_runtime(get_driver(), scheduler)
