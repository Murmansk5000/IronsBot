from __future__ import annotations

import asyncio
import json
import logging
import time
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
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryPolicy
from ironsbot.services.messaging.retry_batches import (
    retry_batch_size,
    run_delivery_batches,
)
from tests.test_bilibili_outbound_delivery import _item
from tests.test_proactive_delivery import FakeMessenger, _delivery

if TYPE_CHECKING:
    from pathlib import Path

TARGET = ConversationRef(Platform.ONEBOT, "group", "100")
TOTAL_ATTEMPTS = 4
TOTAL_SENDS = 8
SECOND_ATTEMPT = 2
INITIAL_STAGE_COUNT = 3
BATCH_SIZE = 3


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(now=time.time(), waits=[])
    original_sleep = asyncio.sleep

    async def sleep(delay: float) -> None:
        state.waits.append(delay)
        state.now += delay
        await original_sleep(0)

    monkeypatch.setattr(
        "ironsbot.integrations.storage.bilibili_delivery_ledger.time",
        SimpleNamespace(time=lambda: state.now),
    )
    monkeypatch.setattr(
        "ironsbot.services.bilibili.outbound_delivery.asyncio.sleep", sleep
    )
    return state


def image_message(url: str) -> OutboundMessage:
    return OutboundMessage((RemoteImagePart(url),))


@pytest.mark.asyncio
async def test_four_rounds_only_failed_unit_and_frozen_manifest(
    tmp_path: Path,
    clock: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    seen = []

    class Messenger(FakeMessenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            self.calls.append((conversation, message))
            image = next(
                (part for part in message.parts if isinstance(part, RemoteImagePart)),
                None,
            )
            if image is not None:
                seen.append(image.url)
                if (
                    image.url.endswith("2.png")
                    and seen.count(image.url) < TOTAL_ATTEMPTS
                ):
                    return SendResult(
                        delivered=False,
                        error_code="upload_timeout",
                        failure_kind=DeliveryFailureKind.RETRYABLE,
                    )
            return SendResult(delivered=True, message_id="ok")

    item = _item()
    item["modules"]["module_dynamic"]["major"]["opus"]["pics"] = [
        {"url": f"https://example.com/{n}.png"} for n in (1, 2, 3)
    ]
    messenger = Messenger()
    delivery, _, subs = _delivery(messenger=messenger)
    ledger = SqliteDynamicDeliveryLedger(
        tmp_path / "ledger.sqlite", media_root=tmp_path / "cache"
    )
    notices = AsyncMock()
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subs),
        ledger=ledger,
        combine_images=False,
        admin_notices=notices,
    )
    await sender.send(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []))
    assert clock.waits == [2.0, 5.0, 10.0]
    assert [url.rsplit("/", 1)[-1] for url in seen] == [
        "1.png",
        "2.png",
        "2.png",
        "2.png",
        "2.png",
        "3.png",
    ]
    assert len(messenger.calls) == TOTAL_SENDS  # Link, text, six image attempts.
    notices.send_private_to_superusers.assert_not_awaited()
    assert ledger.round_count(item["id_str"]) == TOTAL_ATTEMPTS
    assert ledger.state_counts(item["id_str"]) == {"success": 5}
    for number in range(1, TOTAL_ATTEMPTS + 1):
        assert f"round={number}" in caplog.text
    for delay in (2, 5, 10):
        assert f"delay_seconds={delay:.3f}" in caplog.text
    for marker in (
        "Bilibili push started:",
        "Bilibili media ready:",
        "Bilibili target started:",
        "queue_ms=",
        "Bilibili unit delivered:",
        "Bilibili unit failed:",
        "Bilibili round finished:",
        "Bilibili push summary:",
    ):
        assert marker in caplog.text
    assert "https://example.com" not in caplog.text
    with SqliteDatabase(ledger.path).connect() as db:
        assert (
            db.execute("SELECT attempts FROM stages WHERE stage='image:2'").fetchone()[
                0
            ]
            == TOTAL_ATTEMPTS
        )
    await sender.send(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), resume=True
    )
    assert len(messenger.calls) == TOTAL_SENDS


@pytest.mark.asyncio
async def test_restart_respects_remaining_delay_count_and_receipts(
    tmp_path: Path, clock: SimpleNamespace
) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = SqliteDynamicDeliveryLedger(path, media_root=tmp_path / "cache")
    item = _item()
    assert ledger.prepare(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ()
    )
    assert ledger.begin_round(item["id_str"])
    for stage in ("link", "text"):
        assert ledger.claim(item["id_str"], TARGET, stage)
        ledger.finish(
            item["id_str"], TARGET, stage, SendResult(delivered=True, message_id=stage)
        )
    ledger.freeze_media(item["id_str"], image_message("https://example.com/one.png"))
    ledger.image_units(item["id_str"], TARGET, 1)
    assert ledger.claim(item["id_str"], TARGET, "image:1")
    ledger.finish(
        item["id_str"],
        TARGET,
        "image:1",
        SendResult(
            delivered=False,
            error_code="timeout",
            failure_kind=DeliveryFailureKind.RETRYABLE,
        ),
    )
    clock.now += 1
    restarted = SqliteDynamicDeliveryLedger(path, media_root=tmp_path / "cache")
    restarted.recover()
    messenger = FakeMessenger()
    delivery, _, subs = _delivery(messenger=messenger)
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=restarted
    )
    await sender.send(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), resume=True
    )
    assert clock.waits == [1.0]
    assert len(messenger.calls) == 1
    assert restarted.attempts(item["id_str"], TARGET, "image:1") == SECOND_ATTEMPT
    assert restarted.round_count(item["id_str"]) == SECOND_ATTEMPT


@pytest.mark.asyncio
async def test_uncertain_unit_blocks_later_images_and_notifies_once(
    tmp_path: Path, clock: SimpleNamespace
) -> None:
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(delivered=True, message_id="link"),
            SendResult(delivered=True, message_id="text"),
            SendResult(
                delivered=False,
                error_code="message_submit:ReadTimeout",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            ),
        ]
    )
    delivery, _, subs = _delivery(messenger=messenger)
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    notices = AsyncMock()
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=ledger, admin_notices=notices
    )
    await sender.send(
        _item(), int(clock.now), 123, BiliPushTargets([TARGET], [], [], [])
    )
    assert len(messenger.calls) == INITIAL_STAGE_COUNT
    assert clock.waits == []
    notices.send_private_to_superusers.assert_awaited_once()
    assert "已尝试1次" in notices.send_private_to_superusers.await_args.args[0]


def test_frozen_binary_and_legacy_failure_are_not_reprepared(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = SqliteDynamicDeliveryLedger(path, media_root=tmp_path / "cache")
    frozen = OutboundMessage(
        (BinaryImagePart(b"GIF89a-original", "image/gif", "original.gif"),)
    )
    ledger.freeze_media("one", frozen)
    ledger.freeze_media("one", image_message("https://example.com/changed.png"))
    assert ledger.load_media("one") == (True, frozen)
    payload = json.dumps({"id_str": "old", "modules": {}})
    with SqliteDatabase(path).connect() as db:
        db.execute(
            "INSERT INTO deliveries VALUES (?,?,?)", ("old", time.time(), payload)
        )
        db.execute(
            "INSERT INTO stages (dynamic_id,target,stage,state,result) "
            "VALUES (?,?,?,'failed',?)",
            ("old", ledger._target(TARGET), "image", "{}"),
        )
    ledger.recover()
    ledger.image_units("old", TARGET, 3)
    assert not ledger.unattempted("old", TARGET, "image:1")
    assert ledger.failures("old") == []
    next((tmp_path / "cache").iterdir()).unlink()
    with pytest.raises(FileNotFoundError):
        ledger.load_media("one")


@pytest.mark.parametrize(
    "count,limit,expected", [(16, -1, 8), (6, -1, 3), (1, -1, 1), (16, 3, 3)]
)
def test_retry_capacity(count: int, limit: int, expected: int) -> None:
    assert retry_batch_size(count, limit, 2, retry=True) == expected
    assert retry_batch_size(count, limit, 2, retry=False) == (
        count if limit < 0 else min(count, limit)
    )


@pytest.mark.asyncio
async def test_batches_finish_before_next_batch_starts() -> None:
    active = set()
    batches = []
    original_sleep = asyncio.sleep

    async def send(index: int) -> None:
        active.add(index)
        batches.append(tuple(sorted(active)))
        await original_sleep(0)
        active.remove(index)

    await run_delivery_batches(list(range(6)), send, batch_size=3)
    assert max(map(len, batches)) == BATCH_SIZE
    assert not any(BATCH_SIZE - 1 in batch and BATCH_SIZE in batch for batch in batches)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [-1, 2])
async def test_failed_targets_halve_and_next_dynamic_resets(
    tmp_path: Path,
    clock: SimpleNamespace,
    limit: int,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    active: dict[tuple[str, int], int] = {}
    peaks: dict[tuple[str, int], int] = {}
    counts: dict[tuple[str, str], int] = {}
    original_sleep = asyncio.sleep
    current_id = ""

    class Messenger(FakeMessenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            if not any(isinstance(part, RemoteImagePart) for part in message.parts):
                return SendResult(delivered=True, message_id="ok")
            key = (current_id, ledger.round_count(current_id))
            active[key] = active.get(key, 0) + 1
            peaks[key] = max(peaks.get(key, 0), active[key])
            target_key = (current_id, conversation.id)
            counts[target_key] = counts.get(target_key, 0) + 1
            await original_sleep(0)
            active[key] -= 1
            if key[1] == 1:
                return SendResult(
                    delivered=False,
                    error_code="cos_put:timeout",
                    failure_kind=DeliveryFailureKind.RETRYABLE,
                )
            return SendResult(delivered=True, message_id="ok")

    messenger = Messenger()
    delivery, _, subs = _delivery(
        messenger=messenger, policy=ProactiveDeliveryPolicy(max_parallel_targets=limit)
    )
    sender = BilibiliDynamicOutboundSender(delivery, cast("Any", subs), ledger=ledger)
    groups = [ConversationRef(Platform.ONEBOT, "group", str(n)) for n in range(5)]
    private = ConversationRef(Platform.ONEBOT, "private", "private")
    for current_id in ("first", "second"):
        item = _item()
        item["id_str"] = current_id
        await sender.send(
            item, int(clock.now), 123, BiliPushTargets(groups, [], [private], [])
        )
        assert peaks[(current_id, 1)] == (6 if limit < 0 else limit)
        assert peaks[(current_id, 2)] == (3 if limit < 0 else limit)
        assert all(
            counts[(current_id, target.id)] == SECOND_ATTEMPT
            for target in (*groups, private)
        )


@pytest.mark.asyncio
async def test_retry_exhaustion_and_restart_do_not_reset_rounds(
    tmp_path: Path, clock: SimpleNamespace
) -> None:
    class Messenger(FakeMessenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            self.calls.append((conversation, message))
            if any(isinstance(part, RemoteImagePart) for part in message.parts):
                return SendResult(
                    delivered=False,
                    error_code="cos_put:ConnectTimeout",
                    failure_kind=DeliveryFailureKind.RETRYABLE,
                )
            return SendResult(delivered=True, message_id="ok")

    messenger = Messenger()
    delivery, _, subs = _delivery(messenger=messenger)
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    notices = AsyncMock()
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subs), ledger=ledger, admin_notices=notices
    )
    item = _item()
    await sender.send(item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []))
    image_count = sum(
        any(isinstance(part, RemoteImagePart) for part in msg.parts)
        for _, msg in messenger.calls
    )
    assert image_count == TOTAL_ATTEMPTS
    assert clock.waits == [2, 5, 10]
    assert "已尝试4次" in notices.send_private_to_superusers.await_args.args[0]
    ledger.recover()
    await sender.send(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), resume=True
    )
    assert (
        sum(
            any(isinstance(part, RemoteImagePart) for part in msg.parts)
            for _, msg in messenger.calls
        )
        == TOTAL_ATTEMPTS
    )
    notices.send_private_to_superusers.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_finishes_unattempted_units_in_interrupted_final_round(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    assert ledger.prepare(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ()
    )
    for _ in range(TOTAL_ATTEMPTS - 1):
        assert ledger.begin_round(item["id_str"])
        ledger.finish_round(item["id_str"])
    assert ledger.begin_round(item["id_str"])
    for stage in ("link", "text"):
        assert ledger.claim(item["id_str"], TARGET, stage)
        ledger.finish(
            item["id_str"], TARGET, stage, SendResult(delivered=True, message_id="ok")
        )
    ledger.freeze_media(item["id_str"], image_message("https://example.com/frozen.png"))
    ledger.image_units(item["id_str"], TARGET, 1)
    ledger.recover()
    messenger = FakeMessenger()
    delivery, _, subs = _delivery(messenger=messenger)
    sender = BilibiliDynamicOutboundSender(delivery, cast("Any", subs), ledger=ledger)
    await sender.send(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), resume=True
    )
    assert len(messenger.calls) == 1
    assert ledger.round_count(item["id_str"]) == TOTAL_ATTEMPTS
    assert ledger.completed_round_count(item["id_str"]) == TOTAL_ATTEMPTS


@pytest.mark.asyncio
async def test_generic_delivery_call_can_set_delays_without_changing_policy(
    clock: SimpleNamespace,
) -> None:
    transient = SendResult(
        delivered=False,
        error_code="transient",
        failure_kind=DeliveryFailureKind.RETRYABLE,
    )
    messenger = FakeMessenger(
        scripted_results=[
            transient,
            transient,
            transient,
            SendResult(delivered=True, message_id="ok"),
        ]
    )
    delivery, _, _ = _delivery(messenger=messenger)
    original_policy = delivery.policy
    result = await delivery.send(
        OutboundMessage.from_text("test"),
        (TARGET,),
        action_name="test",
        retry_delays_seconds=(2, 5, 10),
        split_failed_targets=True,
    )
    assert clock.waits == [2, 5, 10]
    assert result.succeeded == (TARGET,)
    assert delivery.policy == original_policy


def test_claim_prevents_overtaking_inflight_image_and_early_finalization(
    tmp_path: Path,
    clock: SimpleNamespace,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    dynamic_id = item["id_str"]
    assert ledger.prepare(
        item, int(clock.now), 123, BiliPushTargets([TARGET], [], [], []), ()
    )
    ledger.image_units(dynamic_id, TARGET, 2)
    assert not ledger.claim(dynamic_id, TARGET, "image:2")
    assert ledger.claim(dynamic_id, TARGET, "image:1")
    assert not ledger.skip_remaining(dynamic_id)
    assert ledger.unattempted(dynamic_id, TARGET, "image:2")
    assert not ledger.claim(dynamic_id, TARGET, "image:2")
    ledger.finish(
        dynamic_id, TARGET, "image:1", SendResult(delivered=True, message_id="ok")
    )
    assert ledger.claim(dynamic_id, TARGET, "image:2")
