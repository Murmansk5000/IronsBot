from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import (
    DeliveryFailureKind,
    ExecutionIdentity,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.delivery_ledger import StageMessenger
from ironsbot.services.bilibili.delivery_recovery import BiliStartupRecovery
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_outbound_delivery import _item
from tests.test_proactive_delivery import FakeMessenger, _delivery

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.services.bilibili.targets import BiliTargetService

TARGET = ConversationRef(Platform.ONEBOT, "group", "100")


@pytest.mark.asyncio
async def test_recovery_excludes_new_targets_and_does_not_touch_new_inflight(
    tmp_path: Path,
) -> None:
    ledger = prepare(tmp_path / "delivery.sqlite")
    sender = Mock(ledger=ledger, send=AsyncMock())
    targets = Mock()
    new_target = ConversationRef(Platform.ONEBOT, "group", "101")
    targets.push_targets_for_dynamic.return_value = BiliPushTargets(
        [TARGET, new_target], [], [], []
    )
    recovery = BiliStartupRecovery(
        cast("BilibiliDynamicOutboundSender", sender),
        cast("BiliTargetService", targets),
    )
    assert ledger.claim("1", TARGET, "link")
    await recovery("bot1")
    sender.send.assert_awaited_once()
    assert sender.send.await_args.args[3].full_group_conversations == [TARGET]
    assert sender.send.await_args.kwargs == {"resume": True}
    with SqliteDatabase(ledger.path).connect() as db:
        assert (
            db.execute("SELECT state FROM stages WHERE stage='link'").fetchone()[0]
            == "sending"
        )
    await recovery("bot1")
    sender.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_stage_claim_sends_only_once(tmp_path: Path) -> None:
    import asyncio

    ledger = prepare(tmp_path / "delivery.sqlite")
    messenger = AsyncMock()
    messenger.send.return_value = SendResult(delivered=True, message_id="1")
    stage = StageMessenger(cast("OutboundMessenger", messenger), ledger, "1", "link")
    await asyncio.gather(
        stage.send(TARGET, OutboundMessage.from_text("link")),
        stage.send(TARGET, OutboundMessage.from_text("link")),
    )
    messenger.send.assert_awaited_once()


def prepare(path: Path) -> SqliteDynamicDeliveryLedger:
    ledger = SqliteDynamicDeliveryLedger(path)
    item = {
        "id_str": "1",
        "modules": {"module_dynamic": {"desc": {"text": "body"}}},
    }
    assert ledger.prepare(
        item,
        int(time.time()),
        123,
        BiliPushTargets([TARGET], [], [], []),
        (),
    )
    assert not ledger.prepare(
        item, int(time.time()), 123, BiliPushTargets([], [], [], []), ()
    )
    return ledger


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["success", "failed", "uncertain"])
async def test_attempted_stage_never_replays(tmp_path: Path, state: str) -> None:
    path = tmp_path / "stages.sqlite"
    ledger = prepare(path)
    identity = ExecutionIdentity(Platform.ONEBOT, "200", "executor")
    result = (
        SendResult(delivered=True, message_id="9", execution_identity=identity)
        if state == "success"
        else SendResult(
            delivered=False,
            error_code="failed",
            execution_identity=identity,
            failure_kind=(
                DeliveryFailureKind.UNCERTAIN
                if state == "uncertain"
                else DeliveryFailureKind.RETRYABLE
            ),
        )
    )
    messenger = AsyncMock()
    messenger.send.return_value = result
    stage = StageMessenger(cast("OutboundMessenger", messenger), ledger, "1", "link")
    await stage.send(TARGET, OutboundMessage.from_text("link"))
    restarted = SqliteDynamicDeliveryLedger(path)
    restarted.recover()
    await StageMessenger(
        cast("OutboundMessenger", messenger), restarted, "1", "link"
    ).send(
        TARGET,
        OutboundMessage.from_text("link"),
    )
    messenger.send.assert_awaited_once()
    assert restarted.claim("1", TARGET, "text")
    with SqliteDatabase(path).connect() as db:
        stored = db.execute("SELECT result FROM stages WHERE stage='link'").fetchone()[
            0
        ]
    assert '"account_id": "200"' in stored


def test_restart_abandons_inflight_and_expires_old_work(tmp_path: Path) -> None:
    path = tmp_path / "stages.sqlite"
    ledger = prepare(path)
    assert ledger.claim("1", TARGET, "link")
    ledger.recover()
    assert not ledger.claim("1", TARGET, "link")
    assert len(ledger.pending()) == 1
    with SqliteDatabase(path).connect() as db:
        db.execute("UPDATE deliveries SET created=?", (time.time() - 86401,))
    ledger.recover()
    assert ledger.pending() == []
    assert not ledger.claim("1", TARGET, "text")


def test_offline_does_not_consume_unsent_stage(tmp_path: Path) -> None:
    ledger = prepare(tmp_path / "stages.sqlite")
    assert ledger.claim("1", TARGET, "link")
    ledger.finish(
        "1", TARGET, "link", SendResult(delivered=False, error_code="bot_unavailable")
    )
    ledger.skip_remaining("1")
    ledger.recover()
    assert ledger.claim("1", TARGET, "link")
    assert not ledger.claim("1", TARGET, "text")


@pytest.mark.asyncio
async def test_complete_dynamic_does_not_retry_failed_image_or_repeat_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ironsbot.services.bilibili.outbound_delivery.DYNAMIC_PUSH_INTERVAL_SECONDS", 0
    )
    executor = ExecutionIdentity(Platform.ONEBOT, "200", "任务机器人")
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(delivered=True, message_id="link", execution_identity=executor),
            SendResult(delivered=True, message_id="text", execution_identity=executor),
            SendResult(
                delivered=False,
                error_code="image_failed",
                failure_kind=DeliveryFailureKind.RETRYABLE,
                execution_identity=executor,
            ),
        ]
    )
    delivery, _, subscriptions = _delivery(messenger=messenger)
    notices = AsyncMock()
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "delivery.sqlite")
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        admin_notices=notices,
        ledger=ledger,
    )
    item = _item()
    targets = BiliPushTargets([TARGET], [], [], [])
    await sender.send(item, int(time.time()), 1310714247, targets, ("preview",))
    count = len(messenger.calls)
    assert count == len(("link", "text", "image"))
    await sender.send(item, int(time.time()), 1310714247, targets)
    ledger.recover()
    await sender.send(item, int(time.time()), 1310714247, targets, resume=True)
    assert len(messenger.calls) == count
    notices.send_private_to_superusers.assert_awaited_once()
    text = notices.send_private_to_superusers.await_args.args[0]
    assert "任务机器人（QQ：200）" in text
    assert "赛尔号（UID：1310714247）" in text
