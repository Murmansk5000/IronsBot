# SPDX-License-Identifier: MIT
"""Freeze fully decorated messages before the first send attempt."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent, StoredDelivery

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.messaging.delivery_tasks import DeliveryTaskStore
    from ironsbot.services.messaging.proactive_delivery import (
        ProactiveDeliveryRequest,
        ProactiveMessageDelivery,
    )


def persist_requests(  # noqa: PLR0913 - frozen per-call policy
    delivery: ProactiveMessageDelivery,
    requests: tuple[ProactiveDeliveryRequest, ...],
    *,
    action_name: str,
    subscription_key: str | None,
    include_promotions: bool,
    attempts: int,
    delays: tuple[float, ...] | None,
) -> tuple[ProactiveDeliveryRequest, ...]:
    from ironsbot.services.messaging.proactive_delivery import (
        append_push_promotions,
        append_subscription_hint,
    )

    assert delivery.outbox is not None
    event = uuid.uuid4().hex
    prepared = []
    for request in requests:
        if request.delivery_id:
            prepared.append(request)
            continue
        intent = request.intent or DeliveryIntent(event, time.time() + 86400)
        target = request.conversation
        task_id = hashlib.sha256(
            f"{intent.key}:{target}:{intent.position}".encode()
        ).hexdigest()
        message = request.message
        if include_promotions:
            message = append_push_promotions(
                message,
                conversation=target,
                features=delivery.features,
                promotions=delivery.promotions,
            )
        if subscription_key:
            message = append_subscription_hint(
                message,
                conversation=target,
                config=delivery.unsubscribe,
                subscriptions=delivery.subscriptions,
            )
        message = delivery.outbox.prepare(
            StoredDelivery(
                task_id,
                target,
                message,
                intent,
                action_name,
                subscription_key,
                attempts,
                delays or (delivery.policy.retry_delay_seconds,),
            )
        )
        prepared.append(
            replace(request, message=message, delivery_id=task_id, intent=intent)
        )
    return tuple(prepared)


def record_unavailable(
    store: DeliveryTaskStore | None,
    requests: tuple[ProactiveDeliveryRequest, ...],
    results: dict[ConversationRef, SendResult],
) -> None:
    if store is None:
        return
    for request in requests:
        if request.conversation in results and store.claim(request.delivery_id):
            store.finish(request.delivery_id, results[request.conversation])


async def send_claimed(
    store: DeliveryTaskStore,
    request: ProactiveDeliveryRequest,
    send: Callable[[], Awaitable[SendResult]],
) -> SendResult:
    if not store.claim(request.delivery_id):
        return store.result(request.delivery_id)
    try:
        result = await send()
    except BaseException:
        store.finish(
            request.delivery_id,
            SendResult(
                delivered=False,
                error_code="interrupted_send",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            ),
        )
        raise
    store.finish(request.delivery_id, result)
    if result.delivered:
        try:
            store.wake(
                result.execution_identity.account_id
                if result.execution_identity
                else request.conversation.account_id or "",
                platform=request.conversation.platform,
            )
        except Exception:
            logger.exception("proactive recovery wake failed after receipt commit")
    return result


def allowed_request(
    delivery: ProactiveMessageDelivery,
    request: ProactiveDeliveryRequest,
    subscription: str | None,
) -> bool:
    from ironsbot.core.platform import ActorRef

    target = request.conversation
    actor = ActorRef(target.platform, target.id, account_id=target.account_id)
    if delivery.features.conversation_has_feature(target, "blacklist") or (
        target.kind == "private"
        and delivery.features.actor_has_feature(actor, "blacklist")
    ):
        return False
    if delivery.private_routes is not None:
        route = delivery.private_routes.decision_for(target)
        if route.status == "skipped" or route.target != target:
            return False
    if subscription and not delivery.subscriptions.filter_subscribed_conversations(
        [target], subscription
    ):
        return False
    feature = request.intent.feature if request.intent else ""
    if not feature:
        return True
    return (
        delivery.features.actor_has_feature(actor, feature)
        if target.kind == "private"
        else delivery.features.conversation_has_feature(target, feature)
    )
