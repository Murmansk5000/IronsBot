# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.config.models.features import (
    FeatureConfig,
    build_onebot_feature_service,
)
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)


class FakeAdminNoticeSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_admin_notice(  # noqa: PLR0913
        self,
        message: OutboundMessage,
        *,
        private_actors: tuple[ActorRef, ...],
        group_conversations: tuple[ConversationRef, ...],
        subscription_key: str,
        action_name: str,
        interval_seconds: float,
    ) -> AdminNoticeSendSummary:
        self.calls.append(
            {
                "message": message,
                "private_actors": private_actors,
                "group_conversations": group_conversations,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
                "subscription_key": subscription_key,
            }
        )
        return AdminNoticeSendSummary(private_actors + group_conversations, ())


def _service(
    *,
    with_targets: bool = True,
) -> tuple[AdminNoticeService, FakeAdminNoticeSender]:
    feature_config = FeatureConfig(
        group_policy={"3003": ["admin_notice"]} if with_targets else {},
    )
    sender = FakeAdminNoticeSender()
    return (
        AdminNoticeService(
            build_onebot_feature_service(
                feature_config,
                frozenset((2002, 1001) if with_targets else ()),
            ),
            sender,
        ),
        sender,
    )


def test_admin_notice_targets_use_platform_references() -> None:
    service, _sender = _service()
    targets = service.targets()

    assert targets.private_actors == (
        ActorRef(Platform.ONEBOT, "1001"),
        ActorRef(Platform.ONEBOT, "2002"),
    )
    assert targets.group_conversations == (
        ConversationRef(Platform.ONEBOT, "group", "3003"),
    )


@pytest.mark.asyncio
async def test_send_admin_notice_uses_platform_neutral_targets() -> None:
    service, sender = _service()
    summary = await service.send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert summary.succeeded == (
        ActorRef(Platform.ONEBOT, "1001"),
        ActorRef(Platform.ONEBOT, "2002"),
        ConversationRef(Platform.ONEBOT, "group", "3003"),
    )
    assert sender.calls == [
        {
            "message": OutboundMessage((TextPart("AI聊天接口异常。"),)),
            "private_actors": (
                ActorRef(Platform.ONEBOT, "1001"),
                ActorRef(Platform.ONEBOT, "2002"),
            ),
            "group_conversations": (ConversationRef(Platform.ONEBOT, "group", "3003"),),
            "action_name": "AI chat error notice",
            "subscription_key": "ai_chat_error_notice",
            "interval_seconds": 1.5,
        }
    ]


@pytest.mark.asyncio
async def test_send_admin_notice_skips_when_no_admin_targets() -> None:
    service, sender = _service(with_targets=False)
    summary = await service.send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert summary == AdminNoticeSendSummary((), ())
    assert sender.calls == []


@pytest.mark.asyncio
async def test_private_superuser_notice_never_uses_admin_notice_groups() -> None:
    service, sender = _service()

    await service.send_private_to_superusers(
        "幸运橱窗命中关注皮肤。",
        subscription_key="daily_private_notice",
        action_name="daily private notice",
    )

    assert sender.calls == [
        {
            "message": OutboundMessage((TextPart("幸运橱窗命中关注皮肤。"),)),
            "private_actors": (
                ActorRef(Platform.ONEBOT, "1001"),
                ActorRef(Platform.ONEBOT, "2002"),
            ),
            "group_conversations": (),
            "action_name": "daily private notice",
            "subscription_key": "daily_private_notice",
            "interval_seconds": 1.5,
        }
    ]
