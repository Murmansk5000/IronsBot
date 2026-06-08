import re

from nonebot import on_message, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.superuser_policy import (
    is_group_allowed_for_user,
    is_private_user_allowed,
    with_custom_push_users,
    with_superuser_groups,
    with_superusers,
)
from ironsbot.utils.rule import no_reply

from .config import (
    GroupScheduledMessageAction,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    plugin_config,
)
from .replies import event_sender_at_user_ids, finish_matcher_message
from .senders import send_broadcast_message
from .text import command_text_matches, normalize_command_text

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"


def _job_id(prefix: str, index: int, raw_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id or f"task_{index}")
    safe_id = safe_id.strip("_") or str(index)
    return f"message_action_{prefix}_{safe_id}"


def _private_action_allowed(
    event: PrivateMessageEvent,
    action: PrivateCommandMessageAction,
) -> bool:
    return is_private_user_allowed(
        event.user_id,
        action.allowed_user_ids,
    )


async def _match_private_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    text = normalize_command_text(event.get_plaintext())
    for action in plugin_config.msg_private_commands:
        if not action.enabled or not _private_action_allowed(event, action):
            continue

        if command_text_matches(text, action.commands):
            state[PRIVATE_ACTION_KEY] = action
            return True

    return False


async def _match_group_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    text = normalize_command_text(event.get_plaintext())
    for action in plugin_config.msg_group_commands:
        if not action.enabled:
            continue

        if not is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            action.group_ids,
        ):
            continue

        if command_text_matches(text, action.commands):
            state[GROUP_ACTION_KEY] = action
            return True

    return False


private_command_matcher = on_message(
    rule=Rule(_match_private_command) & no_reply(),
    priority=4,
    block=True,
)

group_command_matcher = on_message(
    rule=Rule(_match_group_command) & no_reply(),
    priority=4,
    block=True,
)


@private_command_matcher.handle()
async def handle_private_command(
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    action = state[PRIVATE_ACTION_KEY]
    await finish_matcher_message(
        private_command_matcher,
        action.message,
        event=event,
    )


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    action = state[GROUP_ACTION_KEY]
    at_user_ids = [
        *event_sender_at_user_ids(event),
        *action.at_user_ids,
    ]
    await finish_matcher_message(
        group_command_matcher,
        action.message,
        at_user_ids=at_user_ids,
        event=event,
    )


async def _send_private_schedule(task: PrivateScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        private_user_ids=with_custom_push_users(with_superusers(task.user_ids)),
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
    )


async def _send_group_schedule(task: GroupScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        group_ids=with_superuser_groups(task.group_ids),
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
    )


def _register_private_schedule(
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    trigger_kwargs: dict[str, int | str] = {
        "hour": task.hour,
        "minute": task.minute,
        "second": 0,
    }
    if task.day_of_week:
        trigger_kwargs["day_of_week"] = task.day_of_week

    scheduler.add_job(
        _send_private_schedule,
        "cron",
        kwargs={"task": task},
        id=_job_id("private_schedule", index, task.id),
        replace_existing=True,
        **trigger_kwargs,
    )


def _register_group_schedule(
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    trigger_kwargs: dict[str, int | str] = {
        "hour": task.hour,
        "minute": task.minute,
        "second": 0,
    }
    if task.day_of_week:
        trigger_kwargs["day_of_week"] = task.day_of_week

    scheduler.add_job(
        _send_group_schedule,
        "cron",
        kwargs={"task": task},
        id=_job_id("group_schedule", index, task.id),
        replace_existing=True,
        **trigger_kwargs,
    )


for _index, _task in enumerate(
    plugin_config.msg_private_schedules,
    start=1,
):
    _register_private_schedule(_index, _task)

for _index, _task in enumerate(
    plugin_config.msg_group_schedules,
    start=1,
):
    _register_group_schedule(_index, _task)
