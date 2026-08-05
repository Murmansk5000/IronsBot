# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.lucky_skin_window import (
    OneBotLuckySkinWindowNotificationSender,
)


class FakeOneBotDelivery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_targets(
        self,
        targets: list[MessageTarget],
        message: str,
        *,
        action_name: str,
        interval_seconds: float,
        subscription_key: str,
    ) -> TargetSendSummary:
        self.calls.append(
            {
                "targets": targets,
                "message": message,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
                "subscription_key": subscription_key,
            }
        )
        return TargetSendSummary(targets, [])


class FakeSubscriptions:
    def __init__(self, *, unsubscribed: bool = False, daily_hint: bool = True) -> None:
        self.unsubscribed = unsubscribed
        self.daily_hint = daily_hint
        self.hint_calls: list[tuple[ConversationRef, str, str]] = []

    def is_unsubscribed(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> bool:
        assert (conversation, subscription_key) == (
            ConversationRef(Platform.ONEBOT, "private", "1001"),
            "lucky_skin_window",
        )
        return self.unsubscribed

    def mark_daily_hint_sent(
        self,
        conversation: ConversationRef,
        hint_key: str,
        *,
        today: str,
    ) -> bool:
        self.hint_calls.append((conversation, hint_key, today))
        return self.daily_hint


@pytest.mark.asyncio
async def test_onebot_lucky_skin_sender_preserves_daily_push_semantics() -> None:
    delivery = FakeOneBotDelivery()
    subscriptions = FakeSubscriptions()
    sender = OneBotLuckySkinWindowNotificationSender(
        delivery,  # type: ignore[arg-type]
        subscriptions,  # type: ignore[arg-type]
    )

    sent = await sender.send_daily_notice(
        ActorRef(Platform.ONEBOT, "1001"),
        "今日幸运橱窗。",
        day="2026-08-05",
    )

    assert sent
    assert subscriptions.hint_calls == [
        (
            ConversationRef(Platform.ONEBOT, "private", "1001"),
            "lucky_skin_window_delivery",
            "2026-08-05",
        )
    ]
    assert delivery.calls == [
        {
            "targets": [MessageTarget("private", 1001)],
            "message": "今日幸运橱窗。",
            "action_name": "lucky skin window daily notice",
            "interval_seconds": 0,
            "subscription_key": "lucky_skin_window",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ("unsubscribed", "duplicate"))
async def test_onebot_lucky_skin_sender_skips_unsubscribed_or_duplicate_notice(
    scenario: str,
) -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotLuckySkinWindowNotificationSender(
        delivery,  # type: ignore[arg-type]
        FakeSubscriptions(
            unsubscribed=scenario == "unsubscribed",
            daily_hint=scenario != "duplicate",
        ),  # type: ignore[arg-type]
    )

    sent = await sender.send_daily_notice(
        ActorRef(Platform.ONEBOT, "1001"),
        "今日幸运橱窗。",
        day="2026-08-05",
    )

    assert not sent
    assert delivery.calls == []
