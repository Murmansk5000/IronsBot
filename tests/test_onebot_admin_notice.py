# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.admin_notice import OneBotAdminNoticeSender


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
        subscription_key: str,
    ) -> TargetSendSummary:
        self.calls.append(
            {
                "message": str(message),
                "private_user_ids": private_user_ids,
                "group_ids": group_ids,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
                "subscription_key": subscription_key,
            }
        )
        return TargetSendSummary(
            [
                MessageTarget("private", 1001),
                MessageTarget("group", 3003),
            ],
            [],
        )


@pytest.mark.asyncio
async def test_onebot_admin_sender_preserves_delivery_routing() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotAdminNoticeSender(delivery)  # type: ignore[arg-type]
    actor = ActorRef(Platform.ONEBOT, "1001")
    conversation = ConversationRef(Platform.ONEBOT, "group", "3003")

    result = await sender.send_admin_notice(
        OutboundMessage((TextPart("数据库同步失败。"),)),
        private_actors=(actor,),
        group_conversations=(conversation,),
        action_name="database notice",
        interval_seconds=1.2,
        subscription_key="database_sync",
    )

    assert delivery.calls == [
        {
            "message": "数据库同步失败。",
            "private_user_ids": (1001,),
            "group_ids": (3003,),
            "action_name": "database notice",
            "interval_seconds": 1.2,
            "subscription_key": "database_sync",
        }
    ]
    assert result.succeeded == (actor, conversation)
    assert result.failed == ()


@pytest.mark.asyncio
async def test_onebot_admin_sender_rejects_non_onebot_targets() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotAdminNoticeSender(delivery)  # type: ignore[arg-type]
    unsupported = ActorRef(Platform.QQ_OFFICIAL, "openid")

    result = await sender.send_admin_notice(
        OutboundMessage((TextPart("数据库同步失败。"),)),
        private_actors=(unsupported,),
        group_conversations=(),
        action_name="database notice",
        interval_seconds=1.2,
        subscription_key="database_sync",
    )

    assert delivery.calls == [
        {
            "message": "数据库同步失败。",
            "private_user_ids": (),
            "group_ids": (),
            "action_name": "database notice",
            "interval_seconds": 1.2,
            "subscription_key": "database_sync",
        }
    ]
    assert result.succeeded == ()
    assert result.failed == (unsupported,)


@pytest.mark.asyncio
async def test_onebot_admin_sender_renders_binary_images() -> None:
    delivery = FakeOneBotDelivery()
    sender = OneBotAdminNoticeSender(delivery)  # type: ignore[arg-type]
    actor = ActorRef(Platform.ONEBOT, "1001")

    await sender.send_admin_notice(
        OutboundMessage(
            (
                TextPart("请重新登录 B站。\n"),
                BinaryImagePart(b"png", "image/png"),
            )
        ),
        private_actors=(actor,),
        group_conversations=(),
        action_name="Bilibili login notice",
        interval_seconds=1.2,
        subscription_key="bili_login_notice",
    )

    assert delivery.calls[0]["message"] == (
        "请重新登录 B站。\n[CQ:image,file=base64://cG5n,cache=true,proxy=true]"
    )
