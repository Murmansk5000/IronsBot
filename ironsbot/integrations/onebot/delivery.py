# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from inspect import isawaitable
from math import ceil
from typing import TYPE_CHECKING, Protocol, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.core.messaging import (
    DeliveryHistoryStatus,
    DeliveryReceipt,
    MessageTarget,
    TargetSendSummary,
    broadcast_targets,
)

from .outbound import (
    GroupOutboundRateLimitService,
    is_outbound_suppressed_result,
    use_preacquired_push_permit,
)
from .push_guard import (
    OneBotTransportCircuit,
    PushBatchCoordinator,
    PushBatchResult,
    TargetSendResult,
    is_transport_unavailable_error,
    is_uncertain_delivery_error,
    ordered_push_targets,
    push_target_sort_key,
)

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import (
        PushDeliveryConfig,
        PushUnsubscribeConfig,
    )
    from ironsbot.services.messaging.delivery import DeliveryReceiptHandler
    from ironsbot.services.messaging.subscriptions import (
        PushDeliverySubscriptions,
        PushTargetType,
    )

    from .router import BotRouter

MessageLimiter = Callable[[str | Message, MessageTarget], str | Message]
PUSH_SUBSCRIPTION_HINT_KEY = "push_subscription_hint"
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


def _message_id_from_result(result: object) -> int | None:
    raw_message_id = (
        result.get("message_id")
        if isinstance(result, Mapping)
        else getattr(result, "message_id", None)
    )
    if isinstance(raw_message_id, bool) or not isinstance(raw_message_id, (int, str)):
        return None
    try:
        message_id = int(raw_message_id)
    except (TypeError, ValueError):
        return None
    return message_id if message_id > 0 else None


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
    _transport_circuit: OneBotTransportCircuit = field(
        default_factory=OneBotTransportCircuit,
        compare=False,
        repr=False,
    )

    def default_bot(self) -> OneBotMessageSender | None:
        return self.bot_router.default_bot()

    def bot_for_target(self, target: MessageTarget) -> OneBotMessageSender | None:
        return self.bot_router.for_target(target)

    def _bot_key(
        self,
        target: MessageTarget,
        explicit_bot: OneBotMessageSender | None,
    ) -> str | None:
        target_bot = explicit_bot or self.bot_router.for_target(target)
        if target_bot is None:
            return None
        return str(getattr(target_bot, "self_id", id(target_bot)))

    def _target_bot_for_send(
        self,
        target: MessageTarget,
        explicit_bot: OneBotMessageSender | None,
        *,
        action_name: str,
        subscription_key: str | None,
    ) -> tuple[OneBotMessageSender | None, TargetSendResult | None]:
        target_bot = explicit_bot or self.bot_router.for_target(target)
        if target_bot is None:
            logger.warning(
                "{} has no connected bot for {} {}",
                action_name,
                target.target_type,
                target.target_id,
            )
            return None, TargetSendResult(sent=False)
        if subscription_key and self._transport_circuit.is_open(target_bot):
            logger.info(
                "{} skipped for {} {} because the OneBot transport circuit is open",
                action_name,
                target.target_type,
                target.target_id,
            )
            return target_bot, TargetSendResult(
                sent=False,
                transport_unavailable=True,
            )
        return target_bot, None

    def _send_error_result(
        self,
        error: Exception,
        *,
        target: MessageTarget,
        target_bot: OneBotMessageSender,
        action_name: str,
    ) -> TargetSendResult:
        transport_unavailable = is_transport_unavailable_error(error)
        if transport_unavailable:
            self._transport_circuit.open(
                target_bot,
                self.push_delivery.transport_failure_cooldown_seconds,
                error,
            )
        logger.warning(
            "{} failed to send to {} {} via bot {}: {}",
            action_name,
            target.target_type,
            target.target_id,
            getattr(target_bot, "self_id", "explicit"),
            error,
        )
        return TargetSendResult(
            sent=False,
            uncertain=is_uncertain_delivery_error(error),
            transport_unavailable=transport_unavailable,
        )

    @staticmethod
    def _restore_target_order(
        summary: TargetSendSummary,
        original_targets: Iterable[MessageTarget],
    ) -> TargetSendSummary:
        succeeded = set(summary.succeeded)
        failed = set(summary.failed)
        uncertain = set(summary.uncertain)
        ordered = list(original_targets)
        return TargetSendSummary(
            [target for target in ordered if target in succeeded],
            [target for target in ordered if target in failed],
            tuple(target for target in ordered if target in uncertain),
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
        receipt_handler: DeliveryReceiptHandler | None = None,
        verify_history: bool = False,
    ) -> TargetSendResult:
        if index > 0 and interval_seconds > 0:
            await asyncio.sleep(index * interval_seconds)

        target_bot, preflight_failure = self._target_bot_for_send(
            target,
            bot,
            action_name=action_name,
            subscription_key=subscription_key,
        )
        if preflight_failure is not None or target_bot is None:
            return preflight_failure or TargetSendResult(sent=False)

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
            return TargetSendResult(sent=False)

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
                return TargetSendResult(sent=False)
        except Exception as e:  # noqa: BLE001
            self.outbound.rollback(decision.permit)
            return self._send_error_result(
                e,
                target=target,
                target_bot=target_bot,
                action_name=action_name,
            )

        self._transport_circuit.close(target_bot)
        message_id = _message_id_from_result(result)
        history_status: DeliveryHistoryStatus = "not_checked"
        history_error: str | None = None
        if verify_history:
            history_status, history_error = await self._verify_message_history(
                target_bot,
                message_id,
            )
        receipt = DeliveryReceipt(
            target=target,
            bot_id=getattr(target_bot, "self_id", None),
            message_id=message_id,
            history_status=history_status,
            history_error=history_error,
        )
        await self._notify_delivery_receipt(receipt_handler, receipt)
        logger.info(
            "{} sent to {} {} via bot {} message_id={} history_status={}",
            action_name,
            target.target_type,
            target.target_id,
            getattr(target_bot, "self_id", "explicit"),
            message_id,
            history_status,
        )
        return TargetSendResult(sent=True, receipt=receipt)

    @staticmethod
    async def _notify_delivery_receipt(
        handler: DeliveryReceiptHandler | None,
        receipt: DeliveryReceipt,
    ) -> None:
        if handler is None:
            return
        try:
            outcome = handler(receipt)
            if isawaitable(outcome):
                await outcome
        except Exception:  # noqa: BLE001
            logger.exception(
                "delivery receipt handler failed: target_type={} target_id={} "
                "message_id={}",
                receipt.target.target_type,
                receipt.target.target_id,
                receipt.message_id,
            )

    @staticmethod
    async def _verify_message_history(
        bot: OneBotMessageSender,
        message_id: int | None,
    ) -> tuple[DeliveryHistoryStatus, str | None]:
        if message_id is None:
            return "missing", "send result did not include a positive message_id"
        get_msg = getattr(bot, "get_msg", None)
        if not callable(get_msg):
            return "unsupported", "OneBot get_msg is unavailable"
        try:
            get_msg_call = cast("Callable[..., Awaitable[object]]", get_msg)
            result = await asyncio.wait_for(
                get_msg_call(message_id=message_id),
                timeout=5.0,
            )
        except Exception as error:  # noqa: BLE001
            return "error", f"{type(error).__name__}: {error}"
        returned_message_id = _message_id_from_result(result)
        if returned_message_id == message_id:
            return "confirmed", None
        return "missing", f"get_msg returned message_id={returned_message_id!r}"

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
        max_attempts: int,
        receipt_handler: DeliveryReceiptHandler | None,
        verify_history: bool,
    ) -> PushBatchResult:
        bot_keys = [
            key
            for target, _message in selected
            if (key := self._bot_key(target, bot)) is not None
        ]
        async with self.batch_coordinator.acquire(bot_keys):
            results: list[TargetSendResult] = []
            parallelism = self.push_delivery.max_parallel_targets
            for start in range(0, len(selected), parallelism):
                chunk = selected[start : start + parallelism]
                chunk_results = await asyncio.gather(
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
                            receipt_handler=receipt_handler,
                            verify_history=verify_history,
                        )
                        for target, message in chunk
                    )
                )
                results.extend(chunk_results)
                if any(result.transport_unavailable for result in chunk_results):
                    break
        attempted = selected[: len(results)]
        succeeded = [
            target
            for (target, _message), result in zip(attempted, results, strict=True)
            if result.sent
        ]
        failed = [
            target
            for (target, _message), result in zip(attempted, results, strict=True)
            if not result.sent
        ] + [target for target, _message in selected[len(results) :]]
        uncertain = tuple(
            target
            for (target, _message), result in zip(attempted, results, strict=True)
            if not result.sent and result.uncertain
        )
        transport_unavailable = any(
            result.transport_unavailable for result in results
        )
        logger.info(
            "{} push attempt {}/{} batch {} size={} targets={} "
            "attempted={} succeeded={} failed={} uncertain={} transport_unavailable={}",
            action_name,
            attempt,
            max_attempts,
            batch_index,
            batch_size,
            len(selected),
            len(results),
            len(succeeded),
            len(failed),
            len(uncertain),
            transport_unavailable,
        )
        return PushBatchResult(
            TargetSendSummary(succeeded, failed, uncertain),
            transport_unavailable,
        )

    async def _send_push_targets(  # noqa: PLR0913
        self,
        selected: list[tuple[MessageTarget, str | Message]],
        *,
        bot: OneBotMessageSender | None,
        action_name: str,
        message_limiter: MessageLimiter | None,
        subscription_key: str,
        retry_failed_targets: bool,
        receipt_handler: DeliveryReceiptHandler | None,
        verify_history: bool,
    ) -> TargetSendSummary:
        pending = selected
        succeeded_targets: set[MessageTarget] = set()
        uncertain_targets: set[MessageTarget] = set()
        batch_size = max(len(pending), 1)
        max_attempts = (
            self.push_delivery.max_attempts if retry_failed_targets else 1
        )
        transport_unavailable = False
        for attempt in range(1, max_attempts + 1):
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
                        max_attempts,
                        batch_index,
                    )
                    await asyncio.sleep(delay)
                batch_result = await self._send_push_batch(
                    batch,
                    bot=bot,
                    action_name=action_name,
                    message_limiter=message_limiter,
                    subscription_key=subscription_key,
                    attempt=attempt,
                    batch_index=batch_index,
                    batch_size=batch_size,
                    max_attempts=max_attempts,
                    receipt_handler=receipt_handler,
                    verify_history=verify_history,
                )
                summary = batch_result.summary
                succeeded_targets.update(summary.succeeded)
                uncertain_targets.update(summary.uncertain)
                failed_ids = set(summary.failed)
                next_pending.extend(
                    item for item in batch if item[0] in failed_ids
                )
                if batch_result.transport_unavailable:
                    later_batches = batches[batch_index:]
                    next_pending.extend(
                        item for later_batch in later_batches for item in later_batch
                    )
                    transport_unavailable = True
                    logger.error(
                        "{} push aborted after OneBot transport failure: "
                        "attempt={}/{} succeeded={} pending={} pending_targets={}",
                        action_name,
                        attempt,
                        max_attempts,
                        len(succeeded_targets),
                        len(next_pending),
                        [
                            f"{target.target_type}:{target.target_id}"
                            for target, _message in next_pending
                        ],
                    )
                    break
            pending = next_pending
            if transport_unavailable:
                break
        return TargetSendSummary(
            [
                target
                for target, _message in selected
                if target in succeeded_targets
            ],
            [target for target, _message in pending],
            tuple(
                target
                for target, _message in selected
                if target in uncertain_targets
            ),
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
        retry_failed_targets: bool = True,
    ) -> TargetSendSummary:
        selected = list(dict.fromkeys(targets))
        if subscription_key:
            selected = self._filter_subscribed_targets(selected, subscription_key)
        original_selected = selected
        selected = ordered_push_targets(
            original_selected,
            group_alias_order=self.group_alias_order,
            user_alias_order=self.user_alias_order,
        )
        if subscription_key:
            summary = await self._send_push_targets(
                [(target, message) for target in selected],
                bot=bot,
                action_name=action_name,
                message_limiter=message_limiter,
                subscription_key=subscription_key,
                retry_failed_targets=retry_failed_targets,
                receipt_handler=None,
                verify_history=False,
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
        summary = TargetSendSummary(
            [
                target
                for target, result in zip(selected, results, strict=True)
                if result.sent
            ],
            [
                target
                for target, result in zip(selected, results, strict=True)
                if not result.sent
            ],
            tuple(
                target
                for target, result in zip(selected, results, strict=True)
                if not result.sent and result.uncertain
            ),
        )
        return self._restore_target_order(summary, original_selected)

    async def send_target_messages(  # noqa: PLR0913
        self,
        target_messages: Iterable[tuple[MessageTarget, str | Message]],
        *,
        bot: OneBotMessageSender | None = None,
        action_name: str = "message action",
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
        retry_failed_targets: bool = True,
        receipt_handler: DeliveryReceiptHandler | None = None,
        verify_history: bool = False,
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
            key=lambda index: push_target_sort_key(
                selected[index][0],
                index,
                group_alias_order=self.group_alias_order,
                user_alias_order=self.user_alias_order,
            ),
        )
        selected = [selected[index] for index in ordered_indexes]
        if subscription_key:
            summary = await self._send_push_targets(
                selected,
                bot=bot,
                action_name=action_name,
                message_limiter=message_limiter,
                subscription_key=subscription_key,
                retry_failed_targets=retry_failed_targets,
                receipt_handler=receipt_handler,
                verify_history=verify_history,
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
                    receipt_handler=receipt_handler,
                    verify_history=verify_history,
                )
                for target, message in selected
            )
        )
        summary = TargetSendSummary(
            [
                target
            for (target, _message), result in zip(selected, results, strict=True)
            if result.sent
            ],
            [
                target
            for (target, _message), result in zip(selected, results, strict=True)
            if not result.sent
            ],
            tuple(
                target
                for (target, _message), result in zip(selected, results, strict=True)
                if not result.sent and result.uncertain
            ),
        )
        return self._restore_target_order(
            summary,
            [target for target, _message in original_selected],
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
        retry_failed_targets: bool = True,
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
            retry_failed_targets=retry_failed_targets,
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
