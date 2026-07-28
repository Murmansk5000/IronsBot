from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import Message

from ironsbot.core.messaging import TargetSendSummary
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.bilibili.delivery import build_dynamic_message
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.delivery import (
    BilibiliPushDeliveryService,
    DynamicPushDelivery,
)
from ironsbot.services.bilibili.targets import BiliPushTargets
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.asyncio
async def test_bilibili_dynamic_push_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[dict[str, object]] = []
    delivery = DynamicPushDelivery(
        message=Message("动态正文"),
        group_ids=[987654321],
        private_user_ids=[1234567890],
        action_name="Bilibili dynamic push",
    )
    monkeypatch.setattr(
        BilibiliPushDeliveryService,
        "build_deliveries",
        lambda *_args: [delivery],
    )

    async def fake_send_broadcast_message(
        _delivery: object,
        _message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.append(kwargs)
        return TargetSendSummary([], [])

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_send_broadcast_message)

    runtime = build_test_runtime()
    service = BilibiliPushDeliveryService(
        runtime.features,
        runtime.delivery,
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        build_dynamic_message,
        append_text_hint,
    )
    await service.send(
        {},
        1,
        1310714247,
        BiliPushTargets([987654321], [], [1234567890], []),
    )

    assert len(sent) == 1
    assert sent[0]["group_ids"] == [987654321]
    assert sent[0]["private_user_ids"] == [1234567890]
    assert "bot" not in sent[0]
