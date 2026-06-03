import asyncio
import re
from collections.abc import Iterable
from typing import Literal, NamedTuple

from nonebot import get_bot, on_message, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.utils.rule import no_reply
from ironsbot.custom_plugins.superuser_policy import (
    is_group_allowed_for_user,
    is_private_user_allowed,
    with_superuser_groups,
    with_superusers,
)

from .config import (
    GroupCommandMessageAction,
    GroupScheduledMessageAction,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    plugin_config,
)

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"


class SendSummary(NamedTuple):
    succeeded: list[int]
    failed: list[int]


class MessageTarget(NamedTuple):
    target_type: Literal["private", "group"]
    target_id: int
    at_user_ids: tuple[int, ...] = ()


class TargetSendSummary(NamedTuple):
    succeeded: list[MessageTarget]
    failed: list[MessageTarget]


def normalize_command_text(text: str) -> str:
    return "".join(text.split())


def command_text_matches(text: str, commands: Iterable[str]) -> bool:
    normalized = normalize_command_text(text)
    return normalized in {
        normalize_command_text(command)
        for command in commands
    }


def _job_id(prefix: str, index: int, raw_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id or f"task_{index}")
    safe_id = safe_id.strip("_") or str(index)
    return f"message_action_{prefix}_{safe_id}"


def _message_text(text: str) -> str:
    return text.replace("\\n", "\n")


def build_message(text: str | Message, at_user_ids: Iterable[int] = ()) -> Message:
    message = Message()

    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")

    if isinstance(text, Message):
        message += text
    else:
        message += MessageSegment.text(_message_text(text))

    return message


def _event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    if not isinstance(event, GroupMessageEvent):
        return ()

    if mention_sender or plugin_config.message_action_mention_group_trigger_user:
        return (event.user_id,)

    return ()


def private_targets(user_ids: Iterable[int]) -> list[MessageTarget]:
    return [
        MessageTarget("private", user_id)
        for user_id in dict.fromkeys(user_ids)
    ]


def group_targets(
    group_ids: Iterable[int],
    *,
    at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    at_users = tuple(dict.fromkeys(at_user_ids))
    return [
        MessageTarget("group", group_id, at_users)
        for group_id in dict.fromkeys(group_ids)
    ]


def broadcast_targets(
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    return [
        *group_targets(group_ids, at_user_ids=group_at_user_ids),
        *private_targets(private_user_ids),
    ]


def _get_bot_or_none() -> Bot | None:
    try:
        return get_bot()
    except Exception as e:
        logger.warning(f"消息动作获取 Bot 失败: {e}")
        return None


async def send_target_messages(
    targets: Iterable[MessageTarget],
    message: str | Message,
    *,
    bot: Bot | None = None,
    action_name: str = "消息动作",
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    deduped_targets = list(dict.fromkeys(targets))
    bot = bot or _get_bot_or_none()
    if not bot:
        return TargetSendSummary([], deduped_targets)

    succeeded: list[MessageTarget] = []
    failed: list[MessageTarget] = []

    for target in deduped_targets:
        rendered_message = build_message(
            message,
            at_user_ids=(
                target.at_user_ids
                if target.target_type == "group"
                else ()
            ),
        )

        try:
            if target.target_type == "private":
                await bot.send_private_msg(
                    user_id=target.target_id,
                    message=rendered_message,
                )
                logger.info(f"{action_name} 已发送给用户 {target.target_id}")
            else:
                await bot.send_group_msg(
                    group_id=target.target_id,
                    message=rendered_message,
                )
                logger.info(f"{action_name} 已发送给群 {target.target_id}")

            succeeded.append(target)
            await asyncio.sleep(interval_seconds)
        except Exception as e:
            failed.append(target)
            logger.warning(
                f"{action_name} 发送到 {target.target_type} "
                f"{target.target_id} 失败: {e}"
            )

    return TargetSendSummary(succeeded, failed)


async def send_broadcast_message(
    message: str | Message,
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
    bot: Bot | None = None,
    action_name: str = "消息动作",
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    return await send_target_messages(
        broadcast_targets(
            private_user_ids=private_user_ids,
            group_ids=group_ids,
            group_at_user_ids=group_at_user_ids,
        ),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )


async def send_private_messages(
    user_ids: Iterable[int],
    message: str | Message,
    *,
    bot: Bot | None = None,
    action_name: str = "消息动作",
    interval_seconds: float = 1.5,
) -> SendSummary:
    summary = await send_target_messages(
        private_targets(user_ids),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )
    return SendSummary(
        [target.target_id for target in summary.succeeded],
        [target.target_id for target in summary.failed],
    )


async def send_group_messages(
    group_ids: Iterable[int],
    message: str | Message,
    *,
    bot: Bot | None = None,
    at_user_ids: Iterable[int] = (),
    action_name: str = "消息动作",
    interval_seconds: float = 1.5,
) -> SendSummary:
    summary = await send_target_messages(
        group_targets(group_ids, at_user_ids=at_user_ids),
        message,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
    )
    return SendSummary(
        [target.target_id for target in summary.succeeded],
        [target.target_id for target in summary.failed],
    )


async def send_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
) -> None:
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
) -> None:
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


async def send_event_reply(
    matcher: Matcher,
    event: MessageEvent,
    message: str | Message,
    *,
    mention_sender: bool = False,
) -> None:
    at_user_ids = _event_sender_at_user_ids(
        event,
        mention_sender=mention_sender,
    )
    await send_matcher_message(matcher, message, at_user_ids=at_user_ids)


async def finish_event_reply(
    matcher: Matcher,
    event: MessageEvent,
    message: str | Message,
    *,
    mention_sender: bool = False,
) -> None:
    at_user_ids = _event_sender_at_user_ids(
        event,
        mention_sender=mention_sender,
    )
    await finish_matcher_message(matcher, message, at_user_ids=at_user_ids)


async def finish_message_sequence(
    matcher: Matcher,
    messages: list[str | Message],
    *,
    event: MessageEvent | None = None,
    mention_sender: bool = False,
    interval_seconds: float = 0.5,
) -> None:
    if not messages:
        return

    at_user_ids = _event_sender_at_user_ids(
        event,
        mention_sender=mention_sender,
    )

    for message in messages[:-1]:
        await send_matcher_message(
            matcher,
            message,
            at_user_ids=at_user_ids,
        )
        await asyncio.sleep(interval_seconds)

    await finish_matcher_message(
        matcher,
        messages[-1],
        at_user_ids=at_user_ids,
    )


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
    for action in plugin_config.message_action_private_commands:
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
    for action in plugin_config.message_action_group_commands:
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
async def handle_private_command(state: T_State) -> None:
    action = state[PRIVATE_ACTION_KEY]
    await finish_matcher_message(private_command_matcher, action.message)


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    action = state[GROUP_ACTION_KEY]
    at_user_ids = [
        *_event_sender_at_user_ids(event),
        *action.at_user_ids,
    ]
    await finish_matcher_message(
        group_command_matcher,
        action.message,
        at_user_ids=at_user_ids,
    )


async def _send_private_schedule(task: PrivateScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        private_user_ids=with_superusers(task.user_ids),
        action_name=f"私聊定时消息 {task.id or '<unnamed>'}",
    )


async def _send_group_schedule(task: GroupScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        group_ids=with_superuser_groups(task.group_ids),
        group_at_user_ids=task.at_user_ids,
        action_name=f"群定时消息 {task.id or '<unnamed>'}",
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
    plugin_config.message_action_private_schedules,
    start=1,
):
    _register_private_schedule(_index, _task)

for _index, _task in enumerate(
    plugin_config.message_action_group_schedules,
    start=1,
):
    _register_group_schedule(_index, _task)
