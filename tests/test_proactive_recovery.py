from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialApiError,
    qq_official_exception_result,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import QQDeliveryPhaseError
from ironsbot.integrations.storage.daily_delivery import SqliteDailyDeliveryStore
from ironsbot.integrations.storage.proactive_tasks import SqliteProactiveTasks
from ironsbot.services.messaging.delivery_recovery import ProactiveRecovery
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent, StoredDelivery
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryPolicy
from ironsbot.services.messaging.scheduled_delivery import ScheduledMessageDelivery
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.lucky_skin_window_recovery import LuckyWindowRecovery
from tests.test_proactive_delivery import ACTOR, GROUP, PRIVATE, _delivery

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetQueryService
    from tests.test_proactive_delivery import FakeFeatures


EXPECTED_SENDS = 2


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    return asyncio.create_task(coro, name=name)


def record(
    key: str = "task",
    *,
    position: int = 0,
    sequence: str = "",
    expires: float | None = None,
    supersedes: str = "",
) -> StoredDelivery:
    return StoredDelivery(
        key,
        GROUP,
        OutboundMessage.from_text(f"message {key}"),
        DeliveryIntent(
            key,
            expires or time.time() + 3600,
            sequence=sequence,
            position=position,
            supersedes=supersedes,
        ),
        "test push",
        None,
        3,
        (0, 0),
    )


def state(store: SqliteProactiveTasks, key: str = "task") -> tuple[str, int]:
    with store.db.connect() as db:
        return db.execute(
            "SELECT state,attempts FROM proactive_tasks WHERE id=?",
            (key,),
        ).fetchone()


def make_due(store: SqliteProactiveTasks) -> None:
    with store.db.connect() as db:
        db.execute("UPDATE proactive_tasks SET next_at=0")


def test_persistent_claim_and_success_receipt(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite"
    first = SqliteProactiveTasks(path)
    second = SqliteProactiveTasks(path)
    first.prepare(record())
    assert first.claim("task")
    assert not second.claim("task")
    first.finish("task", SendResult(delivered=True, message_id="receipt"))
    assert not second.claim("task")
    assert second.result("task").message_id == "receipt"
    assert not second.due()


@pytest.mark.parametrize(
    "kind,expected",
    [
        (DeliveryFailureKind.RETRYABLE, "retry"),
        (DeliveryFailureKind.TRANSPORT_UNAVAILABLE, "waiting"),
        (DeliveryFailureKind.PERMANENT, "permanent"),
        (DeliveryFailureKind.UNCERTAIN, "uncertain"),
    ],
)
def test_failure_dispositions(
    tmp_path: Path, kind: DeliveryFailureKind, expected: str
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    store.prepare(record())
    assert store.claim("task")
    store.finish(
        "task", SendResult(delivered=False, error_code="test", failure_kind=kind)
    )
    assert state(store) == (expected, 0 if expected == "waiting" else 1)
    make_due(store)
    assert bool(store.due()) == (expected in {"retry", "waiting"})


def test_offline_does_not_consume_budget_and_restart_does_not_reset_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "outbox.sqlite"
    store = SqliteProactiveTasks(path)
    store.prepare(record())
    for _ in range(6):
        assert store.claim("task")
        store.finish(
            "task",
            SendResult(
                delivered=False,
                error_code="bot_unavailable",
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            ),
        )
        store.wake()
    assert state(store) == ("waiting", 0)
    for attempt in range(3):
        store = SqliteProactiveTasks(path)
        store.recover()
        make_due(store)
        assert store.claim("task")
        store.finish(
            "task",
            SendResult(
                delivered=False,
                error_code="rate_limit",
                failure_kind=DeliveryFailureKind.RETRYABLE,
            ),
        )
        assert state(store)[1] == attempt + 1
    assert state(store)[0] == "permanent"
    assert not store.claim("task")


def test_interrupted_claim_stays_uncertain(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    store.prepare(record())
    assert store.claim("task")
    store.recover()
    assert state(store)[0] == "uncertain"
    assert not store.due()
    assert not store.claim("task")


def test_sequence_blocks_later_units_until_previous_receipt(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    store.prepare(record("a", sequence="event"))
    store.prepare(record("b", sequence="event", position=1))
    assert not store.claim("b")
    assert store.claim("a")
    store.finish("a", SendResult(delivered=True, message_id="accepted"))
    assert store.claim("b")


def test_frozen_content_and_media_are_not_replaced(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    original = replace(
        record(), message=OutboundMessage((BinaryImagePart(b"image", "image/png"),))
    )
    store.prepare(original)
    restored = store.prepare(record())
    assert restored == original.message
    assert store.due()[0].message == original.message
    next(store.media_root.iterdir()).unlink()
    assert not store.due()
    assert state(store)[0] == "permanent"


def test_expiry_is_fixed_and_status_notifications_supersede(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    store.prepare(record("old", expires=time.time() - 1))
    store.prepare(record("first", supersedes="status"))
    store.prepare(record("latest", supersedes="status"))
    assert [r.id for r in store.due()] == ["latest"]
    assert state(store, "old")[0] == "expired"
    assert state(store, "first")[0] == "superseded"


@pytest.mark.asyncio
async def test_safe_resume_uses_same_content_and_does_not_resend_success(
    tmp_path: Path,
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, _ = _delivery()
    delivery = replace(delivery, outbox=store)
    messenger.scripted_results = [
        SendResult(
            delivered=False,
            error_code="offline",
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
        )
    ]
    await delivery.send(
        OutboundMessage.from_text("original"), (GROUP,), action_name="notice"
    )
    recovery = ProactiveRecovery(delivery, store, spawn)
    await recovery.connected(BotAccountRef(Platform.ONEBOT, "test-bot"))
    await recovery.scan()
    await recovery.scan()
    assert len(messenger.calls) == EXPECTED_SENDS
    assert messenger.calls[0][1] == messenger.calls[1][1]
    assert not store.due()


@pytest.mark.asyncio
async def test_recovery_rechecks_feature_before_send(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, _ = _delivery()
    delivery = replace(delivery, outbox=store)
    task = replace(record(), intent=replace(record().intent, feature="not-granted"))
    store.prepare(task)
    await ProactiveRecovery(delivery, store, spawn).scan()
    assert not messenger.calls
    assert state(store)[0] == "permanent"


@pytest.mark.asyncio
async def test_schedule_registers_whole_sequence_before_offline_send(
    tmp_path: Path,
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, _ = _delivery()
    delivery = replace(
        delivery, outbox=store, policy=ProactiveDeliveryPolicy(retry_delay_seconds=0)
    )
    messenger.scripted_results = [
        SendResult(
            delivered=False,
            error_code="offline",
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
        )
    ]
    await ScheduledMessageOutboundSender(delivery).send(
        ScheduledMessageDelivery(
            ("first", "second"),
            (),
            (GROUP,),
            (),
            "schedule",
            "subscription",
        )
    )
    assert len(messenger.calls) == 1
    assert len(store.due()) == 1  # Second unit is due; first waits for reconnection.
    store.wake()
    await ProactiveRecovery(delivery, store, spawn).scan()
    assert [
        first.text
        for _, m in messenger.calls
        if isinstance(first := m.parts[0], TextPart)
    ] == ["first", "first", "second"]


@pytest.mark.parametrize(
    "phase,error,expected",
    [
        ("upload_prepare", httpx.ReadTimeout("timeout"), DeliveryFailureKind.RETRYABLE),
        ("message_submit", httpx.ReadTimeout("timeout"), DeliveryFailureKind.UNCERTAIN),
        (
            "message_submit",
            httpx.ConnectTimeout("timeout"),
            DeliveryFailureKind.RETRYABLE,
        ),
        (
            "message_submit",
            QQOfficialApiError(
                http_status=500, api_code="500", message="failure", trace_id=None
            ),
            DeliveryFailureKind.UNCERTAIN,
        ),
        (
            "upload_complete",
            QQOfficialApiError(
                http_status=500, api_code="500", message="failure", trace_id=None
            ),
            DeliveryFailureKind.RETRYABLE,
        ),
    ],
)
def test_error_phase_controls_safe_retry(
    phase: str, error: Exception, expected: DeliveryFailureKind
) -> None:
    assert (
        qq_official_exception_result(QQDeliveryPhaseError(phase, error)).failure_kind
        is expected
    )


def test_account_backoff_persists_until_connection_wakes_it(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite"
    store = SqliteProactiveTasks(path)
    store.account_failed(GROUP)
    assert not SqliteProactiveTasks(path).account_ready(GROUP)
    store.wake()
    assert SqliteProactiveTasks(path).account_ready(GROUP)


@pytest.mark.asyncio
async def test_receipt_write_failure_never_blindly_resends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, _ = _delivery()
    delivery = replace(delivery, outbox=store)
    original = store.finish

    def fail_write(_task_id: str, _result: SendResult) -> None:
        message = "storage unavailable"
        raise OSError(message)

    monkeypatch.setattr(store, "finish", fail_write)
    with pytest.raises(OSError, match="storage unavailable"):
        await delivery.send(
            OutboundMessage.from_text("original"), (GROUP,), action_name="notice"
        )
    monkeypatch.setattr(store, "finish", original)
    store.recover()
    await ProactiveRecovery(delivery, store, spawn).scan()
    assert len(messenger.calls) == 1
    assert not store.due()


@pytest.mark.asyncio
async def test_unsubscribed_schedule_does_not_create_recovery_work(
    tmp_path: Path,
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, subscriptions = _delivery()
    subscriptions.allowed = set()
    delivery = replace(delivery, outbox=store)
    await ScheduledMessageOutboundSender(delivery).send(
        ScheduledMessageDelivery(
            ("first", "second"), (), (GROUP,), (), "schedule", "subscription"
        )
    )
    assert not messenger.calls
    assert not store.due()
    assert not store.changes()


@pytest.mark.asyncio
async def test_unsubscribed_tasks_are_not_replayed(tmp_path: Path) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, subscriptions = _delivery()
    delivery = replace(delivery, outbox=store)
    store.prepare(replace(record(), subscription="example"))
    subscriptions.allowed = set()
    await ProactiveRecovery(delivery, store, spawn).scan()
    assert not messenger.calls
    assert state(store)[0] == "permanent"


@pytest.mark.asyncio
async def test_recovered_lucky_menu_uses_frozen_choices_and_records_receipt(
    tmp_path: Path,
) -> None:
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, messenger, _ = _delivery()
    cast("FakeFeatures", delivery.features).enabled_actors.add(
        (ACTOR, "lucky_skin_window")
    )
    delivery = replace(delivery, outbox=store)
    task = replace(
        record(),
        conversation=PRIVATE,
        intent=DeliveryIntent(
            "lucky:qq:1001:2026-10-28",
            time.time() + 300,
            feature="lucky_skin_window",
            source_id=ACTOR.id,
            source_platform=ACTOR.platform.value,
            skin_choices=((900001, 1900001, "示例皮肤"),),
        ),
    )
    store.prepare(task)
    service = Mock(is_eligible_actor=Mock(return_value=True))
    pet = Mock(
        select_image=AsyncMock(
            return_value=SimpleNamespace(reply=None, message="detail")
        )
    )
    sessions = PortableQuerySessions()
    claims = SqliteDailyDeliveryStore(tmp_path / "daily.sqlite")
    handler = LuckyWindowRecovery(
        cast("LuckySkinWindowService", service),
        cast("PetQueryService", pet),
        cast("FeatureService", Mock(is_feature_allowed=Mock(return_value=True))),
        sessions,
        claims,
    )
    worker = ProactiveRecovery(
        delivery,
        store,
        spawn,
        validate=handler.allowed,
        prepare=handler.prepare,
        finished=handler.finished,
    )
    await worker.scan()
    assert len(messenger.calls) == 1
    assert not claims.claim("lucky:qq:1001", "2026-10-28")
    result = await sessions.select("1", handler.context(task))
    assert isinstance(result, OutboundMessage)
    pet.select_image.assert_awaited_once()
    assert pet.select_image.await_args.args[0].skin_id == task.intent.skin_choices[0][0]
