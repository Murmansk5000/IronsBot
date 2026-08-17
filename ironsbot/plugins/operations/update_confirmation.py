# SPDX-License-Identifier: MIT
"""Shared confirmation conversation for manually triggered update work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.commands import parse_confirmation
from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.replies import finish_event_reply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    UpdateExecutor = Callable[[Matcher, MessageEvent, T_State], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class UpdateConfirmation:
    namespace: str
    check_message: str
    action_label: str
    executor: UpdateExecutor


async def request_update_confirmation(
    matcher: Matcher,
    event: MessageEvent,
    confirmation: UpdateConfirmation,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=confirmation.namespace,
        handlers=[
            bind_async(
                _handle_update_confirmation,
                executor=confirmation.executor,
            )
        ],
        reply_check=lambda reply_event: parse_confirmation(reply_event.get_plaintext())
        is not None,
        prompt=(
            f"{confirmation.check_message}\n\n"
            f"是否继续{confirmation.action_label}？\n"
            "回复“是”或“y”确认，回复“否”或“n”取消。"
        ),
    )


async def _handle_update_confirmation(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    executor: UpdateExecutor,
) -> None:
    if parse_confirmation(event.get_plaintext()) is not True:
        await finish_event_reply(matcher, event, "已取消更新。")
        return
    await finish_event_reply(matcher, event, await executor(matcher, event, state))
