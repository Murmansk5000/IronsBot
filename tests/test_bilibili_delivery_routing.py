from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import Message

from ironsbot.core.messaging import TargetSendSummary
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.delivery import BilibiliPushDeliveryService
from ironsbot.services.bilibili.targets import BiliPushTargets
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


EXPECTED_PUSH_COUNT = 2


@pytest.mark.asyncio
async def test_bilibili_dynamic_push_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[dict[str, object]] = []
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
        runtime.delivery,
        PushUnsubscribeStore(tmp_path / "push_subscriptions.sqlite"),
        lambda _item, _pub_ts: Message("链接"),
        lambda _item, _content: Message("动态正文"),
        append_text_hint,
        partial(append_fire_manual_ad_for_target, runtime.features),
    )
    await service.send(
        {
            "modules": {
                "module_dynamic": {
                    "desc": {"text": "动态正文"},
                }
            }
        },
        1,
        1310714247,
        BiliPushTargets([987654321], [], [1234567890], []),
    )

    assert len(sent) == EXPECTED_PUSH_COUNT
    for entry in sent:
        assert entry["group_ids"] == [987654321]
        assert entry["private_user_ids"] == [1234567890]
        assert "bot" not in entry
