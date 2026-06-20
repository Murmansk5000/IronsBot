# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger

from .targets import MessageTarget, TargetSendSummary, broadcast_targets
from .text import build_message

MessageLimiter = Callable[[str | Message, int | None], str | Message]
_message_limiter: MessageLimiter | None = None


class OneBotMessageSender(Protocol):
    async def send_private_msg(self, *, user_id: int, message: Message) -> object:
        ...

    async def send_group_msg(self, *, group_id: int, message: Message) -> object:
        ...


def get_bot_or_none() -> OneBotMessageSender | None:
    try:
        return get_bot()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"message action failed to get bot: {e}")
        return None


def configure_sender_message_limiter(
    message_limiter: MessageLimiter | None,
) -> None:
    global _message_limiter

    _message_limiter = message_limiter


async def send_target_messages(  # noqa: PLR0913
    targets: Iterable[MessageTarget],
    message: str | Message,
    *,
    bot: OneBotMessageSender | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
    message_limiter: MessageLimiter | None = None,
) -> TargetSendSummary:
    deduped_targets = list(dict.fromkeys(targets))
    bot = bot or get_bot_or_none()
    if not bot:
        return TargetSendSummary([], deduped_targets)

    succeeded: list[MessageTarget] = []
    failed: list[MessageTarget] = []

    for target in deduped_targets:
        group_id = target.target_id if target.target_type == "group" else None
        active_limiter = message_limiter or _message_limiter
        limited_message = (
            active_limiter(message, group_id)
            if active_limiter is not None
            else message
        )
        rendered_message = build_message(
            limited_message,
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
            else:
                await bot.send_group_msg(
                    group_id=target.target_id,
                    message=rendered_message,
                )

            logger.info(
                f"{action_name} sent to {target.target_type} {target.target_id}"
            )
            succeeded.append(target)
            await asyncio.sleep(interval_seconds)
        except Exception as e:  # noqa: BLE001
            failed.append(target)
            logger.warning(
                f"{action_name} failed to send to {target.target_type} "
                f"{target.target_id}: {e}"
            )

    return TargetSendSummary(succeeded, failed)


async def send_broadcast_message(  # noqa: PLR0913
    message: str | Message,
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
    bot: OneBotMessageSender | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
    message_limiter: MessageLimiter | None = None,
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
        message_limiter=message_limiter,
    )
