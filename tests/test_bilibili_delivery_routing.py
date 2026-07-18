from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import Message

from ironsbot.plugins.bilibili import service
from ironsbot.services.bilibili.delivery import DynamicPushDelivery
from ironsbot.services.bilibili.targets import BiliPushTargets
from ironsbot.shared.messaging.targets import TargetSendSummary
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.mark.asyncio
async def test_bilibili_dynamic_push_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []
    delivery = DynamicPushDelivery(
        message=Message("动态正文"),
        group_ids=[987654321],
        private_user_ids=[1234567890],
        action_name="Bilibili dynamic push",
    )
    monkeypatch.setattr(
        service,
        "build_dynamic_push_deliveries",
        lambda *_args: [delivery],
    )

    async def fake_send_broadcast_message(
        _delivery: object,
        _message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.append(kwargs)
        return TargetSendSummary([], [])

    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    await service._send_dynamic_push(
        build_test_runtime().admin_notices,
        {},
        1,
        1310714247,
        BiliPushTargets([987654321], [], [1234567890], []),
    )

    assert len(sent) == 1
    assert sent[0]["group_ids"] == [987654321]
    assert sent[0]["private_user_ids"] == [1234567890]
    assert "bot" not in sent[0]
