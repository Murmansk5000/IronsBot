# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from nonebot import logger
from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.tasks import TaskSpawner  # noqa: TC001
from ironsbot.runtime.conversations import (
    command_reply_check,
    enter_event_reply_conversation,
)
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.replies import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.player_query import (
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_DETAIL_TASK_KEY,
    PlayerDetailMessages,
    cached_player_detail_message,
    plan_player_detail_prompt,
    player_detail_auto_reply_keys,
    player_detail_auto_reply_tasks,
    player_detail_empty_message,
    player_detail_failure_message,
    player_detail_pending_message,
    player_detail_timeout_message,
    resolve_player_detail_reply,
    store_player_detail_messages,
)

from .player_context import (
    PLAYER_DETAIL_NAMESPACE,
    PLAYER_ERROR_FORMATTER_KEY,
    PLAYER_ID_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    PlayerErrorFormatter = Callable[
        [int, SocketRecvError | NotLoggedInError | DisconnectedError],
        str,
    ]


async def handle_player_detail_reply(
    spawn: TaskSpawner,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    detail_request = resolve_player_detail_reply(event.get_plaintext())
    detail_is_pending = _is_player_detail_task_pending(state)
    detail_task = state.get(PLAYER_DETAIL_TASK_KEY)
    if (
        detail_request is not None
        and detail_is_pending
        and isinstance(detail_task, asyncio.Task)
    ):
        _schedule_player_detail_auto_reply(
            spawn,
            matcher,
            event,
            state,
            key=detail_request.key,
            label=detail_request.label,
            task=detail_task,
        )
    message = (
        await _get_player_detail_message(
            state,
            detail_request.key,
            detail_request.label,
        )
        if detail_request is not None
        else None
    )

    if not message:
        raise FinishedException

    if detail_is_pending:
        await send_event_reply(
            matcher,
            event,
            message,
        )
        await _continue_player_detail_conversation(
            spawn,
            matcher,
            event,
            state,
            prompt=None,
        )

    await _continue_player_detail_conversation(
        spawn,
        matcher,
        event,
        state,
        prompt=message,
    )


async def send_player_info_with_detail_prompt(  # noqa: PLR0913
    spawn: TaskSpawner,
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    player_message: str,
    error_formatter: PlayerErrorFormatter,
    detail_task: asyncio.Task[PlayerDetailMessages] | None = None,
    has_collection: bool = False,
    has_peak: bool = False,
    has_autocard: bool = False,
) -> None:
    prompt_plan = plan_player_detail_prompt(
        has_collection=has_collection,
        has_peak=has_peak,
        has_autocard=has_autocard,
        supports_conversation=isinstance(event, MessageEvent),
    )

    if detail_task is not None:
        state[PLAYER_DETAIL_TASK_KEY] = detail_task

    state[PLAYER_DETAIL_COMMANDS_KEY] = prompt_plan.commands
    state[PLAYER_ERROR_FORMATTER_KEY] = error_formatter

    if not prompt_plan.should_enter_conversation:
        if isinstance(event, MessageEvent):
            await finish_event_reply(
                matcher,
                event,
                player_message,
            )
        else:
            await matcher.finish(player_message)

    if not isinstance(event, MessageEvent):
        await matcher.finish(player_message)

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[bind_async(handle_player_detail_reply, spawn)],
        reply_check=command_reply_check(prompt_plan.commands),
        prompt=player_message,
    )


async def _get_player_detail_message(
    state: T_State,
    key: str,
    label: str,
) -> str:
    task = state.get(PLAYER_DETAIL_TASK_KEY)
    if isinstance(task, asyncio.Task):
        if not task.done():
            return player_detail_pending_message(label)

        try:
            detail_messages = task.result()
        except TimeoutError:
            state[PLAYER_DETAIL_TASK_KEY] = None
            return player_detail_timeout_message(label)
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as e:
            state[PLAYER_DETAIL_TASK_KEY] = None
            formatter = state.get(PLAYER_ERROR_FORMATTER_KEY)
            return (
                cast("PlayerErrorFormatter", formatter)(
                    int(state.get(PLAYER_ID_KEY, 0)),
                    e,
                )
                if callable(formatter)
                else player_detail_failure_message(label, e)
            )
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("米米号后台详情任务失败")
            state[PLAYER_DETAIL_TASK_KEY] = None
            return player_detail_failure_message(label, e)

        store_player_detail_messages(state, detail_messages)
        state[PLAYER_DETAIL_TASK_KEY] = None

    return cached_player_detail_message(state, key)


def _is_player_detail_task_pending(state: T_State) -> bool:
    task = state.get(PLAYER_DETAIL_TASK_KEY)
    return isinstance(task, asyncio.Task) and not task.done()


def _schedule_player_detail_auto_reply(  # noqa: PLR0913
    spawn: TaskSpawner,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    key: str,
    label: str,
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    auto_reply_keys = player_detail_auto_reply_keys(state)
    if key in auto_reply_keys:
        return

    auto_reply_keys.add(key)
    auto_reply_task = spawn(
        _send_player_detail_auto_reply(
            matcher,
            event,
            state,
            key=key,
            label=label,
            task=task,
        ),
        name=f"seer-player-detail-reply-{event.user_id}-{key}",
    )
    auto_reply_tasks = player_detail_auto_reply_tasks(state)
    auto_reply_tasks.add(auto_reply_task)
    auto_reply_task.add_done_callback(auto_reply_tasks.discard)


async def _send_player_detail_auto_reply(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    key: str,
    label: str,
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    try:
        with suppress(Exception):
            await asyncio.shield(task)

        message = await _get_player_detail_message(state, key, label)
        if not message:
            message = player_detail_empty_message(label)

        await send_event_reply(
            matcher,
            event,
            message,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"米米号后台详情自动回复失败：{e}")
    finally:
        player_detail_auto_reply_keys(state).discard(key)


async def _continue_player_detail_conversation(
    spawn: TaskSpawner,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    prompt: str | None,
) -> None:
    commands = tuple(state.get(PLAYER_DETAIL_COMMANDS_KEY) or ())
    if not commands:
        if prompt is None:
            raise FinishedException
        await finish_event_reply(
            matcher,
            event,
            prompt,
        )

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[bind_async(handle_player_detail_reply, spawn)],
        reply_check=command_reply_check(commands),
        prompt=prompt,
    )
