# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING, Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.core.messaging import (
    MessageTarget,
    TargetSendSummary,
    broadcast_targets,
)

from .outbound import (
    GroupOutboundRateLimitService,
    is_outbound_suppressed_result,
    use_preacquired_push_permit,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ironsbot.config.models.messaging import (
        PushDeliveryConfig,
        PushUnsubscribeConfig,
    )
    from ironsbot.services.messaging.subscriptions import (
        PushDeliverySubscriptions,
        PushTargetType,
    )

    from .router import BotRouter

MessageLimiter = Callable[[str | Message, MessageTarget], str | Message]
PUSH_SUBSCRIPTION_HINT_KEY = "push_subscription_hint"


@dataclass(slots=True)
class PushBatchCoordinator:
    """Prevent concurrent background batches from overloading one QQ client."""

    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _locks_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def acquire(self, bot_keys: Iterable[str]) -> AsyncIterator[None]:
        keys = sorted(set(bot_keys))
        async with self._locks_guard:
            locks = [self._locks.setdefault(key, asyncio.Lock()) for key in keys]
        for lock in locks:
            await lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()


def _copy_outbound_message(message: str | Message) -> str | Message:
    return message.copy() if isinstance(message, Message) else message


def _build_message(
    content: str | Message,
    at_user_ids: Iterable[int],
) -> Message:
    message = Message()
    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")
    message += (
        content
        if isinstance(content, Message)
        else MessageSegment.text(content.replace("\\n", "\n"))
    )
    return message


def _append_unsubscribe_hint(
    message: str | Message,
    config: PushUnsubscribeConfig,
    target_type: PushTargetType,
    target_id: int,
    store: PushDeliverySubscriptions,
) -> str | Message:
    hint = (config.group_hint if target_type == "group" else config.hint).strip()
    if not hint or not store.mark_daily_hint_sent(
        target_type,
        target_id,
        PUSH_SUBSCRIPTION_HINT_KEY,
    ):
        return message.rstrip() if isinstance(message, str) else message
    if isinstance(message, Message):
        if hint not in str(message):
            message += MessageSegment.text(f"\n\n{hint}")
        return message
    text = message.rstrip()
    return text if hint in text else hint if not text else f"{text}\n\n{hint}"


class OneBotMessageSender(Protocol):
    async def send_private_msg(self, *, user_id: int, message: Message) -> object: ...

    async def send_group_msg(self, *, group_id: int, message: Message) -> object: ...


@dataclass(frozen=True, slots=True)
class OneBotDelivery:
    outbound: GroupOutboundRateLimitService
    push_unsubscribe: PushUnsubscribeConfig
    bot_router: BotRouter
    subscriptions: PushDeliverySubscriptions
    push_delivery: PushDeliveryConfig
    group_alias_order: tuple[int, ...] = ()
    user_alias_order: tuple[int, ...] = ()
    batch_coordinator: PushBatchCoordinator = field(
        default_factory=PushBatchCoordinator
    )

    def default_bot(self) -> OneBotMessageSender | None:
        return self.bot_router.default_bot()

    def bot_for_target(self, target: MessageTarget) -> OneBotMessageSender | None:
        return self.bot_router.for_target(target)

    def _ordered_push_targets(
        self,
        targets: Iterable[MessageTarget],
    ) -> list[MessageTarget]:
        return [
            target
            for index, target in sorted(
                enumerate(targets),
                key=lambda item: self._push_target_sort_key(item[1], item[0]),
            )
        ]

    def _push_target_sort_key(
        self,
        target: MessageTarget,
        index: int,
    ) -> tuple[int, int, int, int]:
        target_type_order = 0 if target.target_type == "group" else 1
        aliases = (
            self.group_alias_order if target_type_order == 0 else self.user_alias_order
        )
        alias_order = {
            target_id: position for position, target_id in enumerate(aliases)
        }
        position = alias_order.get(target.target_id)
        return (
            target_type_order,
            0 if position is not None else 1,
            position if position is not None else target.target_id,
            index,
        )

    def _bot_key(
        self,
        target: MessageTarget,
        explicit_bot: OneBotMessageSender | None,
    ) -> str | None:
        target_bot = explicit_bot or self.bot_router.for_target(target)
        if target_bot is None:
            return None
        return str(getattr(target_bot, "self_id", id(target_bot)))

    @staticmethod
    def _restore_target_order(
        summary: TargetSendSummary,
        original_targets: Iterable[MessageTarget],
    ) -> TargetSendSummary:
        succeeded = set(summary.succeeded)
        failed = set(summary.failed)
        ordered = list(original_targets)
        return TargetSendSummary(
            [target for target in ordered if target in succeeded],
            [target for target in ordered if target in failed],
        )

    async def _send_target(  # noqa: PLR0913
        self,
        target: MessageTarget,
        message: str | Message,
        *,
        index: int,
        bot: OneBotMessageSender | None,
        action_name: str,
        interval_seconds: float,
        message_limiter: MessageLimiter | None,
        subscription_key: str | None,
    ) -> bool:
        if index > 0 and interval_seconds > 0:
            await asyncio.sleep(index * interval_seconds)

        target_bot = bot or self.bot_router.for_target(target)
        if target_bot is None:
            logger.warning(
                f"{action_name} has no connected bot for "
                f"{target.target_type} {target.target_id}"
            )
            return False

        limited_message = _copy_outbound_message(message)
        if message_limiter is not None:
            limited_message = message_limiter(limited_message, target)
        group_id = target.target_id if target.target_type == "group" else None
        if subscription_key:
            limited_message = _append_unsubscribe_hint(
                limited_message,
                self.push_unsubscribe,
                target.target_type,
                target.target_id,
                self.subscriptions,
            )
        rendered_message = _build_message(
            limited_message,
            (
                target.at_user_ids if target.target_type == "group" else ()
            ),
        )

        decision = await self.outbound.acquire_push(group_id, source=action_name)
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
                with use_preacquired_push_permit(self.outbound, decision.permit):
                    result = await target_bot.send_group_msg(
                        group_id=target.target_id,
                        message=rendered_message,
                    )
            if is_outbound_suppressed_result(result):
                self.outbound.rollback(decision.permit)
                logger.warning(
                    f"{action_name} was suppressed while sending to "
                    f"{target.target_type} {target.target_id}"
                )
                return False
        except Exception as e:  # noqa: BLE001
            self.outbound.rollback(decision.permit)
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

    async def _send_push_batch(  # noqa: PLR0913
        self,
        selected: list[tuple[MessageTarget, str | Message]],
        *,
        bot: OneBotMessageSender | None,
        action_name: str,
        message_limiter: MessageLimiter | None,
        subscription_key: str,
        attempt: int,
        batch_index: int,
        batch_size: int,
    ) -> TargetSendSummary:
        bot_keys = [
            key
            for target, _message in selected
            if (key := self._bot_key(target, bot)) is not None
        ]
        async with self.batch_coordinator.acquire(bot_keys):
            results = await asyncio.gather(
                *(
                    self._send_target(
                        target,
                        message,
                        index=0,
                        bot=bot,
                        action_name=action_name,
                        interval_seconds=0.0,
                        message_limiter=message_limiter,
                        subscription_key=subscription_key,
                    )
                    for target, message in selected
                )
            )
        succeeded = [
            target
            for (target, _message), sent in zip(selected, results, strict=True)
            if sent
        ]
        failed = [
            target
            for (target, _message), sent in zip(selected, results, strict=True)
            if not sent
        ]
        logger.info(
            "{} push attempt {}/{} batch {} size={} targets={} succeeded={} failed={}",
            action_name,
            attempt,
            self.push_delivery.max_attempts,
            batch_index,
            batch_size,
            len(selected),
            len(succeeded),
            len(failed),
        )
        return TargetSendSummary(succeeded, failed)

    async def _send_push_targets(
        self,
        selected: list[tuple[MessageTarget, str | Message]],
        *,
        bot: OneBotMessageSender | None,
        action_name: str,
        message_limiter: MessageLimiter | None,
        subscription_key: str,
    ) -> TargetSendSummary:
        pending = selected
        succeeded_targets: set[MessageTarget] = set()
        batch_size = max(len(pending), 1)
        for attempt in range(1, self.push_delivery.max_attempts + 1):
            if not pending:
                break
            if attempt > 1:
                batch_size = max(
                    1,
                    ceil(batch_size / self.push_delivery.retry_batch_divisor),
                )
            next_pending: list[tuple[MessageTarget, str | Message]] = []
            batches = [
                pending[index : index + batch_size]
                for index in range(0, len(pending), batch_size)
            ]
            for batch_index, batch in enumerate(batches, start=1):
                if attempt > 1 or batch_index > 1:
                    delay = random.uniform(  # nosec B311 - intentionally jittered
                        self.push_delivery.batch_delay_min_seconds,
                        self.push_delivery.batch_delay_max_seconds,
                    )
                    logger.info(
                        "{} push waiting {:.2f}s before attempt {}/{} batch {}",
                        action_name,
                        delay,
                        attempt,
                        self.push_delivery.max_attempts,
                        batch_index,
                    )
                    await asyncio.sleep(delay)
                summary = await self._send_push_batch(
                    batch,
                    bot=bot,
                    action_name=action_name,
                    message_limiter=message_limiter,
                    subscription_key=subscription_key,
                    attempt=attempt,
                    batch_index=batch_index,
                    batch_size=batch_size,
                )
                succeeded_targets.update(summary.succeeded)
                failed_ids = set(summary.failed)
                next_pending.extend(
                    item for item in batch if item[0] in failed_ids
                )
            pending = next_pending
        return TargetSendSummary(
            [
                target
                for target, _message in selected
                if target in succeeded_targets
            ],
            [target for target, _message in pending],
        )

    async def send_targets(  # noqa: PLR0913
        self,
        targets: Iterable[MessageTarget],
        message: str | Message,
        *,
        bot: OneBotMessageSender | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        selected = list(dict.fromkeys(targets))
        if subscription_key:
            selected = self._filter_subscribed_targets(selected, subscription_key)
            original_selected = selected
            selected = self._ordered_push_targets(original_selected)
            summary = await self._send_push_targets(
                [(target, message) for target in selected],
                bot=bot,
                action_name=action_name,
                message_limiter=message_limiter,
                subscription_key=subscription_key,
            )
            return self._restore_target_order(summary, original_selected)

        results = await asyncio.gather(
            *(
                self._send_target(
                    target,
                    message,
                    index=index,
                    bot=bot,
                    action_name=action_name,
                    interval_seconds=interval_seconds,
                    message_limiter=message_limiter,
                    subscription_key=subscription_key,
                )
                for index, target in enumerate(selected)
            )
        )
        return TargetSendSummary(
            [
                target
                for target, sent in zip(selected, results, strict=True)
                if sent
            ],
            [
                target
                for target, sent in zip(selected, results, strict=True)
                if not sent
            ],
        )

    async def send_target_messages(
        self,
        target_messages: Iterable[tuple[MessageTarget, str | Message]],
        *,
        bot: OneBotMessageSender | None = None,
        action_name: str = "message action",
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        selected = list(target_messages)
        if subscription_key:
            allowed = set(
                self._filter_subscribed_targets(
                    [target for target, _message in selected],
                    subscription_key,
                )
            )
            selected = [
                (target, message)
                for target, message in selected
                if target in allowed
            ]
            original_selected = selected
            ordered_indexes = sorted(
                range(len(selected)),
                key=lambda index: self._push_target_sort_key(
                    selected[index][0], index
                ),
            )
            summary = await self._send_push_targets(
                [selected[index] for index in ordered_indexes],
                bot=bot,
                action_name=action_name,
                message_limiter=message_limiter,
                subscription_key=subscription_key,
            )
            return self._restore_target_order(
                summary,
                [target for target, _message in original_selected],
            )

        results = await asyncio.gather(
            *(
                self._send_target(
                    target,
                    message,
                    index=0,
                    bot=bot,
                    action_name=action_name,
                    interval_seconds=0.0,
                    message_limiter=message_limiter,
                    subscription_key=subscription_key,
                )
                for target, message in selected
            )
        )
        return TargetSendSummary(
            [
                target
                for (target, _message), sent in zip(selected, results, strict=True)
                if sent
            ],
            [
                target
                for (target, _message), sent in zip(selected, results, strict=True)
                if not sent
            ],
        )

    async def broadcast(  # noqa: PLR0913
        self,
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
        return await self.send_targets(
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
        self,
        targets: list[MessageTarget],
        subscription_key: str,
    ) -> list[MessageTarget]:
        private_ids = set(
            self.subscriptions.filter_subscribed_user_ids(
                [
                    target.target_id
                    for target in targets
                    if target.target_type == "private"
                ],
                subscription_key,
            )
        )
        group_ids = set(
            self.subscriptions.filter_subscribed_group_ids(
                [
                    target.target_id
                    for target in targets
                    if target.target_type == "group"
                ],
                subscription_key,
            )
        )
        return [
            target
            for target in targets
            if (target.target_type == "private" and target.target_id in private_ids)
            or (target.target_type == "group" and target.target_id in group_ids)
        ]
