# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.team_resource import (
    OneBotTeamResourceNoticeSender,
)
from ironsbot.services.team.resource import TeamResourceSubscriptionTarget


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
    ) -> TargetSendSummary:
        self.calls.append(
            {
                "targets": targets,
                "message": message,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
            }
        )
        return TargetSendSummary(targets, [])


@pytest.mark.asyncio
async def test_onebot_team_resource_sender_routes_group_mentions() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotTeamResourceNoticeSender(delivery)  # type: ignore[arg-type]

    sent = await sender.send_low_resource_notice(
        TeamResourceSubscriptionTarget(
            ConversationRef(Platform.ONEBOT, "group", "1001"),
            (ActorRef(Platform.ONEBOT, "2001"),),
        ),
        "战队资源不足。",
    )

    assert sent
    assert delivery.calls == [
        {
            "targets": [MessageTarget("group", 1001, (2001,))],
            "message": "战队资源不足。",
            "action_name": "team resource subscription notice",
            "interval_seconds": 0,
        }
    ]


@pytest.mark.asyncio
async def test_onebot_team_resource_sender_rejects_non_onebot_targets() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotTeamResourceNoticeSender(delivery)  # type: ignore[arg-type]

    sent = await sender.send_low_resource_notice(
        TeamResourceSubscriptionTarget(
            ActorRef(Platform.QQ_OFFICIAL, "openid-1001"),
        ),
        "战队资源不足。",
    )

    assert not sent
    assert delivery.calls == []
