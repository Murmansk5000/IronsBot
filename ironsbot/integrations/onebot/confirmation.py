# SPDX-License-Identifier: MIT
"""Reusable yes/no conversations for explicit administrative actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.commands import parse_confirmation
from ironsbot.integrations.onebot.conversations import enter_event_reply_conversation
from ironsbot.integrations.onebot.matchers import bind_async
from ironsbot.integrations.onebot.replies import finish_event_reply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    ConfirmationExecutor = Callable[
        [Matcher, MessageEvent, T_State], Awaitable[str]
    ]


@dataclass(frozen=True, slots=True)
class EventConfirmation:
    namespace: str
    check_message: str
    action_label: str
    executor: ConfirmationExecutor


async def request_event_confirmation(
    matcher: Matcher,
    event: MessageEvent,
    confirmation: EventConfirmation,
) -> None:
    """Ask an event owner to confirm a previously checked side effect."""

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=confirmation.namespace,
        handlers=[
            bind_async(
                _handle_event_confirmation,
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


async def _handle_event_confirmation(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    executor: ConfirmationExecutor,
) -> None:
    if parse_confirmation(event.get_plaintext()) is not True:
        await finish_event_reply(matcher, event, "已取消。")
        return
    await finish_event_reply(matcher, event, await executor(matcher, event, state))
