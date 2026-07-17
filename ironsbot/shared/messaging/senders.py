# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol

from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger

from ironsbot.config.loader import get_app_config

from .bot_router import get_bot_for_target, get_default_bot
from .outbound_rate_limit import (
    group_outbound_rate_limit_service,
    is_outbound_suppressed_result,
    use_preacquired_push_permit,
)
from .push_subscription_store import PushUnsubscribeStore
from .push_subscriptions import append_push_unsubscribe_hint
from .targets import MessageTarget, TargetSendSummary, broadcast_targets
from .text import build_message

MessageLimiter = Callable[[str | Message, int | None], str | Message]


def _copy_outbound_message(message: str | Message) -> str | Message:
    return message.copy() if isinstance(message, Message) else message


class OneBotMessageSender(Protocol):
    async def send_private_msg(self, *, user_id: int, message: Message) -> object: ...

    async def send_group_msg(self, *, group_id: int, message: Message) -> object: ...


def get_bot_or_none() -> OneBotMessageSender | None:
    return get_default_bot()


async def _send_target_message(  # noqa: PLR0913
    target: MessageTarget,
    message: str | Message,
    *,
    index: int,
    bot: OneBotMessageSender | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
    message_limiter: MessageLimiter | None = None,
    subscription_key: str | None = None,
) -> bool:
    if index > 0 and interval_seconds > 0:
        await asyncio.sleep(index * interval_seconds)

    target_bot = bot or get_bot_for_target(target)
    if target_bot is None:
        logger.warning(
            f"{action_name} has no connected bot for "
            f"{target.target_type} {target.target_id}"
        )
        return False

    group_id = target.target_id if target.target_type == "group" else None
    target_message = _copy_outbound_message(message)
    limited_message = (
        message_limiter(target_message, group_id)
        if message_limiter is not None
        else target_message
    )
    if subscription_key:
        limited_message = append_push_unsubscribe_hint(
            limited_message,
            get_app_config().message.push_unsubscribe,
            target_type=target.target_type,
            target_id=target.target_id,
        )
    rendered_message = build_message(
        limited_message,
        at_user_ids=(target.at_user_ids if target.target_type == "group" else ()),
    )

    decision = await group_outbound_rate_limit_service.acquire_push(
        group_id,
        source=action_name,
    )
    if not decision.allowed:
        logger.warning(
            f"{action_name} dropped by outbound push queue for "
            f"{target.target_type} {target.target_id}: {decision.reason}"
        )
        return False

    try:
        if target.target_type == "private":
            result = await target_bot.send_private_msg(
                user_id=target.target_id,
                message=rendered_message,
            )
        else:
            with use_preacquired_push_permit(decision.permit):
                result = await target_bot.send_group_msg(
                    group_id=target.target_id,
                    message=rendered_message,
                )
        if is_outbound_suppressed_result(result):
            group_outbound_rate_limit_service.rollback(decision.permit)
            logger.warning(
                f"{action_name} was suppressed while sending to "
                f"{target.target_type} {target.target_id}"
            )
            return False
    except Exception as e:  # noqa: BLE001
        group_outbound_rate_limit_service.rollback(decision.permit)
        logger.warning(
            f"{action_name} failed to send to {target.target_type} "
            f"{target.target_id} via bot "
            f"{getattr(target_bot, 'self_id', 'explicit')}: {e}"
        )
        return False

    logger.info(
        f"{action_name} sent to {target.target_type} {target.target_id} "
        f"via bot {getattr(target_bot, 'self_id', 'explicit')}"
    )
    return True


async def send_target_messages(  # noqa: PLR0913
    targets: Iterable[MessageTarget],
    message: str | Message,
    *,
    bot: OneBotMessageSender | None = None,
    action_name: str = "message action",
    interval_seconds: float = 1.5,
    message_limiter: MessageLimiter | None = None,
    subscription_key: str | None = None,
) -> TargetSendSummary:
    deduped_targets = list(dict.fromkeys(targets))
    if subscription_key:
        deduped_targets = _filter_subscribed_targets(deduped_targets, subscription_key)

    results = await asyncio.gather(
        *(
            _send_target_message(
                target,
                message,
                index=index,
                bot=bot,
                action_name=action_name,
                interval_seconds=interval_seconds,
                message_limiter=message_limiter,
                subscription_key=subscription_key,
            )
            for index, target in enumerate(deduped_targets)
        )
    )
    succeeded = [
        target
        for target, was_sent in zip(deduped_targets, results, strict=True)
        if was_sent
    ]
    failed = [
        target
        for target, was_sent in zip(deduped_targets, results, strict=True)
        if not was_sent
    ]
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
    subscription_key: str | None = None,
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
        subscription_key=subscription_key,
    )


def _filter_subscribed_targets(
    targets: list[MessageTarget],
    subscription_key: str,
) -> list[MessageTarget]:
    config = get_app_config().message.push_unsubscribe
    store = PushUnsubscribeStore(config.data_path)
    private_ids = store.filter_subscribed_user_ids(
        [target.target_id for target in targets if target.target_type == "private"],
        subscription_key,
    )
    group_ids = store.filter_subscribed_group_ids(
        [target.target_id for target in targets if target.target_type == "group"],
        subscription_key,
    )
    allowed_private_ids = set(private_ids)
    allowed_group_ids = set(group_ids)
    return [
        target
        for target in targets
        if (target.target_type == "private" and target.target_id in allowed_private_ids)
        or (target.target_type == "group" and target.target_id in allowed_group_ids)
    ]
