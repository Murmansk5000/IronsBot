# SPDX-License-Identifier: MIT
"""Platform-neutral batching for proactive outbound messages.

This service owns the policy common to configured pushes.  Platform adapters
only implement ``OutboundMessenger``; they never need to recreate scheduling,
unsubscribe, promotion, or result-accounting loops.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, reference_digest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.config.models.messaging import PushUnsubscribeConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.core.promotions import PromotionCatalog, PromotionConfig
    from ironsbot.services.messaging.subscriptions import PushDeliverySubscriptions


_LOGGER = logging.getLogger(__name__)
_SUBSCRIPTION_HINT_KEY = "push_subscription_hint"


@dataclass(frozen=True, slots=True)
class ProactiveDeliveryRequest:
    """One proactive message addressed to one typed conversation."""

    conversation: ConversationRef
    message: OutboundMessage


@dataclass(frozen=True, slots=True)
class ProactiveDeliverySummary:
    """The exact typed destinations accepted or rejected by the transport."""

    succeeded: tuple[ConversationRef, ...]
    failed: tuple[ConversationRef, ...]
    uncertain: tuple[ConversationRef, ...] = ()
    results: tuple[tuple[ConversationRef, SendResult], ...] = ()


@dataclass(frozen=True, slots=True)
class ProactiveDeliveryPolicy:
    max_attempts: int = 3
    max_parallel_targets: int = 5
    retry_batch_divisor: int = 3
    retry_delay_seconds: float = 2.0


@dataclass(slots=True)
class _DeliveryState:
    succeeded: set[ConversationRef] = field(default_factory=set)
    failed: set[ConversationRef] = field(default_factory=set)
    uncertain: set[ConversationRef] = field(default_factory=set)
    results: dict[ConversationRef, SendResult] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProactiveMessageDelivery:
    """Apply shared push policy before delegating each send to a messenger."""

    messenger: OutboundMessenger
    features: FeatureService
    promotions: PromotionCatalog
    subscriptions: PushDeliverySubscriptions
    unsubscribe: PushUnsubscribeConfig
    policy: ProactiveDeliveryPolicy = field(default_factory=ProactiveDeliveryPolicy)

    async def send(  # noqa: PLR0913 - explicit active delivery policy controls
        self,
        message: OutboundMessage,
        conversations: Iterable[ConversationRef],
        *,
        action_name: str,
        interval_seconds: float = 1.5,
        subscription_key: str | None = None,
        include_promotions: bool = False,
        max_attempts: int | None = None,
    ) -> ProactiveDeliverySummary:
        """Deliver one message to many conversations with shared push policy."""

        return await self.send_many(
            (
                ProactiveDeliveryRequest(conversation, message)
                for conversation in conversations
            ),
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
            include_promotions=include_promotions,
            max_attempts=max_attempts,
        )

    async def send_many(  # noqa: PLR0913 - per-call delivery policy
        self,
        requests: Iterable[ProactiveDeliveryRequest],
        *,
        action_name: str,
        interval_seconds: float = 1.5,
        subscription_key: str | None = None,
        include_promotions: bool = False,
        max_attempts: int | None = None,
    ) -> ProactiveDeliverySummary:
        """Deliver per-conversation messages without exposing adapter targets."""

        selected = _unique_requests(requests)
        if subscription_key:
            selected = self._filter_subscribed(selected, subscription_key)
        if not selected:
            return ProactiveDeliverySummary((), ())

        pending = list(selected)
        state = _DeliveryState()
        attempts = max(1, max_attempts or self.policy.max_attempts)
        for attempt in range(1, attempts + 1):
            if not pending:
                break
            if attempt > 1 and self.policy.retry_delay_seconds > 0:
                await asyncio.sleep(self.policy.retry_delay_seconds)
            batch_size = max(
                1,
                ceil(
                    self.policy.max_parallel_targets
                    / self.policy.retry_batch_divisor ** (attempt - 1)
                ),
            )
            next_pending, transport_unavailable = await self._run_attempt(
                pending,
                state,
                batch_size=batch_size,
                action_name=action_name,
                interval_seconds=interval_seconds,
                subscription_key=subscription_key,
                include_promotions=include_promotions,
            )
            if transport_unavailable:
                break
            if attempt == attempts:
                state.failed.update(request.conversation for request in next_pending)
                break
            pending = next_pending
        summary = ProactiveDeliverySummary(
            tuple(
                request.conversation
                for request in selected
                if request.conversation in state.succeeded
            ),
            tuple(
                request.conversation
                for request in selected
                if request.conversation in state.failed
            ),
            tuple(
                request.conversation
                for request in selected
                if request.conversation in state.uncertain
            ),
            tuple(state.results.items()),
        )
        skipped = sum(
            1
            for result in state.results.values()
            if not result.delivered and not result.attempted
        )
        if skipped:
            _LOGGER.info(
                "%s skipped %d target(s) before a platform send attempt",
                action_name,
                skipped,
            )
        return summary

    async def _run_attempt(  # noqa: PLR0913 - explicit delivery controls
        self,
        pending: list[ProactiveDeliveryRequest],
        state: _DeliveryState,
        *,
        batch_size: int,
        action_name: str,
        interval_seconds: float,
        subscription_key: str | None,
        include_promotions: bool,
    ) -> tuple[list[ProactiveDeliveryRequest], bool]:
        next_pending: list[ProactiveDeliveryRequest] = []
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            results = await asyncio.gather(
                *(
                    self._send_one(
                        request,
                        index=index,
                        action_name=action_name,
                        interval_seconds=interval_seconds,
                        subscription_key=subscription_key,
                        include_promotions=include_promotions,
                    )
                    for index, request in enumerate(batch)
                )
            )
            self._record_batch(batch, results, state, next_pending)
        return next_pending, False

    @staticmethod
    def _record_batch(
        batch: list[ProactiveDeliveryRequest],
        results: list[SendResult],
        state: _DeliveryState,
        next_pending: list[ProactiveDeliveryRequest],
    ) -> bool:
        transport_unavailable = False
        for request, result in zip(batch, results, strict=True):
            state.results[request.conversation] = result
            kind = result.failure_kind or DeliveryFailureKind.PERMANENT
            if result.delivered:
                state.succeeded.add(request.conversation)
            elif kind is DeliveryFailureKind.RETRYABLE:
                next_pending.append(request)
            else:
                state.failed.add(request.conversation)
                if kind is DeliveryFailureKind.UNCERTAIN:
                    state.uncertain.add(request.conversation)
                transport_unavailable |= (
                    kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
                )
        return transport_unavailable

    def _filter_subscribed(
        self,
        requests: tuple[ProactiveDeliveryRequest, ...],
        subscription_key: str,
    ) -> tuple[ProactiveDeliveryRequest, ...]:
        allowed = set(
            self.subscriptions.filter_subscribed_conversations(
                [request.conversation for request in requests],
                subscription_key,
            )
        )
        return tuple(request for request in requests if request.conversation in allowed)

    async def _send_one(  # noqa: PLR0913 - one request plus explicit policy controls
        self,
        request: ProactiveDeliveryRequest,
        *,
        index: int,
        action_name: str,
        interval_seconds: float,
        subscription_key: str | None,
        include_promotions: bool,
    ) -> SendResult:
        if index > 0 and interval_seconds > 0:
            await asyncio.sleep(index * interval_seconds)

        capabilities = self.messenger.capabilities_for(request.conversation)
        if not capabilities.can_send_proactively:
            _LOGGER.warning(
                "%s skipped unsupported conversation: platform=%s kind=%s ref=%s",
                action_name,
                request.conversation.platform.value,
                request.conversation.kind,
                reference_digest(request.conversation.id),
            )
            return SendResult(
                delivered=False,
                error_code="unsupported_conversation",
                attempted=False,
                failure_kind=DeliveryFailureKind.PERMANENT,
            )

        message = request.message
        if include_promotions:
            message = append_push_promotions(
                message,
                conversation=request.conversation,
                features=self.features,
                promotions=self.promotions,
            )
        if subscription_key:
            message = append_subscription_hint(
                message,
                conversation=request.conversation,
                config=self.unsubscribe,
                subscriptions=self.subscriptions,
            )
        try:
            result = await self.messenger.send(request.conversation, message)
        except Exception:
            _LOGGER.exception(
                "%s raised while sending: platform=%s kind=%s ref=%s",
                action_name,
                request.conversation.platform.value,
                request.conversation.kind,
                reference_digest(request.conversation.id),
            )
            return SendResult(
                delivered=False,
                error_code="delivery_exception",
                failure_kind=DeliveryFailureKind.RETRYABLE,
            )
        if result.delivered:
            return result
        _LOGGER.warning(
            "%s failed: platform=%s kind=%s ref=%s code=%s failure_kind=%s trace_id=%s",
            action_name,
            request.conversation.platform.value,
            request.conversation.kind,
            reference_digest(request.conversation.id),
            result.error_code,
            result.failure_kind.value if result.failure_kind is not None else None,
            result.trace_id,
        )
        return result


def append_push_promotions(
    message: OutboundMessage,
    *,
    conversation: ConversationRef,
    features: FeatureService,
    promotions: PromotionCatalog,
) -> OutboundMessage:
    """Append configured push promotions allowed for one typed conversation."""

    result = message
    for promotion in promotions.push_promotions:
        if not _promotion_enabled(features, conversation, promotion):
            continue
        result = append_outbound_text_once(result, promotion.message, promotion.url)
    return result


def append_subscription_hint(
    message: OutboundMessage,
    *,
    conversation: ConversationRef,
    config: PushUnsubscribeConfig,
    subscriptions: PushDeliverySubscriptions,
) -> OutboundMessage:
    """Append the configured daily subscription hint exactly once per target."""

    hint = (config.group_hint if conversation.kind == "group" else config.hint).strip()
    if not hint or not subscriptions.mark_daily_hint_sent(
        conversation,
        _SUBSCRIPTION_HINT_KEY,
    ):
        return message
    return append_outbound_text_once(message, hint)


def _unique_requests(
    requests: Iterable[ProactiveDeliveryRequest],
) -> tuple[ProactiveDeliveryRequest, ...]:
    selected: dict[ConversationRef, ProactiveDeliveryRequest] = {}
    for request in requests:
        selected.setdefault(request.conversation, request)
    return tuple(selected.values())


def _promotion_enabled(
    features: FeatureService,
    conversation: ConversationRef,
    promotion: PromotionConfig,
) -> bool:
    if conversation.kind == "private":
        return features.actor_has_feature(
            ActorRef(conversation.platform, conversation.id),
            promotion.feature,
        )
    return features.conversation_has_feature(conversation, promotion.feature)


def append_outbound_text_once(
    message: OutboundMessage,
    text: str,
    url: str = "",
) -> OutboundMessage:
    rendered = "".join(
        part.text for part in message.parts if isinstance(part, TextPart)
    )
    if text in rendered or (url and url in rendered):
        return message
    return OutboundMessage((*message.parts, TextPart(f"\n\n{text}")))
