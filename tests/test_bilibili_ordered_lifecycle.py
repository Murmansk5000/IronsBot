from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    OutboundMessage,
    RemoteImagePart,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.services.bilibili.delivery_lifecycle import OrderedStages
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_outbound_delivery import _item
from tests.test_proactive_delivery import FakeMessenger, _delivery, _text

ATTEMPT_LIMIT = 4
STAGE_LIMIT = 60

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    value = SimpleNamespace(now=time.time(), waits=[])
    sleep = asyncio.sleep

    async def advance(seconds: float) -> None:
        value.waits.append(seconds)
        value.now += seconds
        await sleep(0)

    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_ledger.time",
        SimpleNamespace(time=lambda: value.now),
    )
    monkeypatch.setattr(
        "ironsbot.services.bilibili.outbound_delivery.asyncio.sleep", advance
    )
    return value


def stage(message: OutboundMessage) -> str:
    if any(isinstance(p, (BinaryImagePart, RemoteImagePart)) for p in message.parts):
        return "image"
    return "link" if "t.bilibili.com/" in _text(message) else "text"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("kind", list(DeliveryFailureKind)[:3])
async def test_predecessor_retry_terminal_and_uncertain(
    tmp_path: Path,
    clock: SimpleNamespace,
    platform: Platform,
    kind: DeliveryFailureKind,
) -> None:
    seen = []

    class Messenger(FakeMessenger):
        def capabilities_for(self, conversation: ConversationRef):
            return replace(
                super().capabilities_for(conversation),
                can_send_proactively=True,
                supports_images=True,
            )

        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            seen.append(stage(message))
            self.calls.append((conversation, message))
            if len(seen) == 1:
                return SendResult(
                    delivered=False, error_code="synthetic_failure", failure_kind=kind
                )
            return SendResult(delivered=True, message_id="receipt")

    target = ConversationRef(
        platform, "group", "synthetic-group", account_id="synthetic-bot"
    )
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    delivery, _, subs = _delivery(messenger=Messenger())
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=ledger, admin_notices=AsyncMock()
    )
    item = _item()
    await sender.send(
        item, int(clock.now), 700001, BiliPushTargets([target], [], [], [])
    )
    if kind is DeliveryFailureKind.UNCERTAIN:
        assert seen == ["link"]
        assert ledger.stage_state(item["id_str"], target, "text") == "blocked"
    else:
        expected = (
            ["link", "link", "text", "image"]
            if kind is DeliveryFailureKind.RETRYABLE
            else ["link", "text", "image"]
        )
        assert seen == expected
    assert ledger.acquire_execution(item["id_str"], "new-owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stages", [("link",), ("link", "text")])
async def test_exhausted_known_failure_continues_after_four_attempts(
    tmp_path: Path, clock: SimpleNamespace, failed_stages: tuple[str, ...]
) -> None:
    seen = []

    class Messenger(FakeMessenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            del conversation
            label = stage(message)
            seen.append(label)
            return (
                SendResult(
                    delivered=False,
                    error_code="connect_failed",
                    failure_kind=DeliveryFailureKind.RETRYABLE,
                )
                if label in failed_stages
                else SendResult(delivered=True, message_id="receipt")
            )

    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    delivery, _, subs = _delivery(messenger=Messenger())
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=ledger, admin_notices=AsyncMock()
    )
    item = _item()
    await sender.send(
        item, int(clock.now), 700001, BiliPushTargets([target], [], [], [])
    )
    assert seen == ["link"] * ATTEMPT_LIMIT + (
        ["text"] * ATTEMPT_LIMIT if "text" in failed_stages else ["text"]
    ) + ["image"]
    assert ledger.attempts(item["id_str"], target, "link") == ATTEMPT_LIMIT
    assert ledger.stage_state(item["id_str"], target, "link") == "failed"


@pytest.mark.parametrize(
    "late_kind", [None, DeliveryFailureKind.PERMANENT, DeliveryFailureKind.RETRYABLE]
)
def test_deadline_persists_and_late_receipt_does_not_unblock(
    tmp_path: Path, clock: SimpleNamespace, late_kind: DeliveryFailureKind | None
) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = SqliteDynamicDeliveryLedger(path)
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    item = _item()
    key = item["id_str"]
    ledger.prepare(
        item, int(clock.now), 700001, BiliPushTargets([target], [], [], []), ()
    )
    assert ledger.start_stage(key, target, "link") == STAGE_LIMIT
    assert ledger.claim(key, target, "link")
    clock.now += 61
    ledger = SqliteDynamicDeliveryLedger(path)
    assert ledger.start_stage(key, target, "link") == 0
    ledger.expire_stage(key, target, "link")
    ledger.block_following(key, target, "link")
    assert ledger.stage_state(key, target, "link") == "uncertain"
    ledger.finish(
        key,
        target,
        "link",
        SendResult(
            delivered=late_kind is None,
            message_id="late-receipt",
            error_code="late-rejection" if late_kind is not None else None,
            failure_kind=late_kind,
        ),
    )
    assert ledger.stage_state(key, target, "link") == (
        "success" if late_kind is None else "failed"
    )
    assert ledger.stage_state(key, target, "text") == "blocked"
    assert not ledger.claim(key, target, "text")


@pytest.mark.asyncio
async def test_queue_deadline_is_known_unsent_and_worker_cannot_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_lifecycle.STAGE_SECONDS", 0.02
    )
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    item = _item()
    key = item["id_str"]
    ledger.prepare(
        item, int(time.time()), 700001, BiliPushTargets([target], [], [], []), ()
    )
    ordered = OrderedStages(ledger, key, {}, set())
    gate = asyncio.Event()
    finished = asyncio.Event()

    async def queued() -> None:
        await gate.wait()
        assert not ledger.claim(key, target, "link")
        finished.set()

    await ordered.run(target, "link", queued)
    assert ledger.stage_state(key, target, "link") == "failed"
    assert ordered.advance(target, "link")
    gate.set()
    await finished.wait()


@pytest.mark.asyncio
async def test_sender_instances_and_recovery_share_one_execution(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class Messenger(FakeMessenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            self.calls.append((conversation, message))
            if stage(message) == "link":
                entered.set()
                await release.wait()
            return SendResult(delivered=True, message_id="receipt")

    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    messenger = Messenger()
    delivery, _, subs = _delivery(messenger=messenger)
    path = tmp_path / "ledger.sqlite"
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=SqliteDynamicDeliveryLedger(path)
    )
    recovery = replace(sender, ledger=SqliteDynamicDeliveryLedger(path))
    assert recovery.ledger is not None
    item = _item()
    targets = BiliPushTargets([target], [], [], [])
    first = asyncio.create_task(sender.send(item, int(time.time()), 700001, targets))
    await entered.wait()
    recovery.ledger.recover()
    await recovery.send(item, int(time.time()), 700001, targets, resume=True)
    assert len(messenger.calls) == 1
    release.set()
    await first
    assert [stage(message) for _, message in messenger.calls] == [
        "link",
        "text",
        "image",
    ]


def test_expired_owner_cannot_release_replacement_or_block_other_target(
    tmp_path: Path, clock: SimpleNamespace
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    a = ConversationRef(Platform.ONEBOT, "group", "synthetic-a")
    b = replace(a, id="synthetic-b")
    item = _item()
    key = item["id_str"]
    ledger.prepare(
        item, int(clock.now), 700001, BiliPushTargets([a, b], [], [], []), ()
    )
    assert ledger.acquire_execution(key, "first-owner")
    assert ledger.claim(key, a, "link")
    clock.now += 31
    assert ledger.acquire_execution(key, "replacement-owner")
    ledger.release_execution(key, "first-owner")
    assert ledger.renew_execution(key, "replacement-owner")
    assert ledger.stage_state(key, a, "link") == "uncertain"
    assert ledger.stage_state(key, a, "text") == "blocked"
    assert ledger.stage_state(key, b, "text") == "pending"
    assert ledger.claim(key, b, "link")


@pytest.mark.asyncio
async def test_inflight_deadline_is_uncertain_not_a_safe_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_lifecycle.STAGE_SECONDS", 0.02
    )
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    item = _item()
    key = item["id_str"]
    ledger.prepare(
        item, int(time.time()), 700001, BiliPushTargets([target], [], [], []), ()
    )
    ordered = OrderedStages(ledger, key, {}, set())
    release = asyncio.Event()
    done = asyncio.Event()

    async def submitted() -> None:
        assert ledger.claim(key, target, "link")
        await release.wait()
        ledger.finish(
            key, target, "link", SendResult(delivered=True, message_id="late")
        )
        done.set()

    await ordered.run(target, "link", submitted)
    assert ledger.stage_state(key, target, "link") == "uncertain"
    assert not ordered.advance(target, "link")
    release.set()
    await done.wait()
    assert ledger.stage_state(key, target, "link") == "success"
    assert ledger.stage_state(key, target, "text") == "blocked"
