# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.activity import OneBotActivityReminderSender
from ironsbot.services.activity.delivery import ActivityReminderDelivery


class FakeOneBotDelivery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def broadcast(  # noqa: PLR0913
        self,
        message: object,
        *,
        private_user_ids: tuple[int, ...],
        group_ids: tuple[int, ...],
        action_name: str,
        interval_seconds: float,
        message_limiter: object,
        subscription_key: str,
    ) -> TargetSendSummary:
        self.calls.append(
            {
                "message": str(message),
                "private_user_ids": private_user_ids,
                "group_ids": group_ids,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
                "message_limiter": message_limiter,
                "subscription_key": subscription_key,
            }
        )
        return TargetSendSummary([MessageTarget("group", 3003)], [])


@pytest.mark.asyncio
async def test_onebot_activity_sender_preserves_push_delivery_semantics() -> None:
    delivery = FakeOneBotDelivery()
    limiter = object()
    sender = OneBotActivityReminderSender(
        delivery,  # type: ignore[arg-type]
        limiter,  # type: ignore[arg-type]
    )

    sent = await sender.send(
        ActivityReminderDelivery(
            status="send",
            message=OutboundMessage((TextPart("活动即将结束。"),)),
            group_conversations=(ConversationRef(Platform.ONEBOT, "group", "3003"),),
            private_actors=(ActorRef(Platform.ONEBOT, "1001"),),
            action_name="activity ending reminder 1h",
        )
    )

    assert sent
    assert delivery.calls == [
        {
            "message": "活动即将结束。",
            "private_user_ids": (1001,),
            "group_ids": (3003,),
            "action_name": "activity ending reminder 1h",
            "interval_seconds": 1.2,
            "message_limiter": limiter,
            "subscription_key": "seer_activity_push",
        }
    ]


@pytest.mark.asyncio
async def test_onebot_activity_sender_skips_delivery_without_a_message() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotActivityReminderSender(
        delivery,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    sent = await sender.send(ActivityReminderDelivery(status="skip_empty"))

    assert not sent
    assert delivery.calls == []
