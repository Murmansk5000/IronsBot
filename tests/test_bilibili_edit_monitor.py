from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.bilibili_revisions import SqliteBiliRevisionStore
from ironsbot.services.bilibili.edit_monitor import BiliEditMonitor
from ironsbot.services.bilibili.push import build_dynamic_history_snapshot_for_item
from ironsbot.services.bilibili.service import BiliFeedResponse
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.helpers.bilibili import build_test_bilibili_service
from tests.test_bilibili_conversation_queue import drain
from tests.test_bilibili_revisions import UID, item

DETAIL_BUDGET = 10
CONCURRENCY = 2
AUTH_BAD = -101

if TYPE_CHECKING:
    from pathlib import Path


class Targets:
    def monitored_uids(self) -> tuple[int, ...]:
        return (UID,)

    def suppress_patterns_for_uid(self, _uid: int) -> list[str]:
        return []

    def category_config_for_uid(self, _uid: int) -> None:
        return None

    def push_targets_for_dynamic(
        self, _uid: int, *, categories: tuple = ()
    ) -> BiliPushTargets:
        del categories
        return BiliPushTargets(
            [ConversationRef(Platform.ONEBOT, "group", "test-group")], [], [], []
        )


def save(service: Any, data: dict, published: int) -> None:
    snapshot = build_dynamic_history_snapshot_for_item(
        data, pub_ts=published, suppress_patterns=[]
    )
    assert snapshot is not None
    service.history.save_snapshot(snapshot)


@pytest.mark.asyncio
async def test_startup_baseline_and_transactional_outbox_without_history_dependency(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    service = build_test_bilibili_service(tmp_path)
    service.targets = cast("Any", Targets())
    owner = TaskOwner()
    service.spawn = owner.create
    save(service, item("already edited before upgrade"), now)
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    ledger = SqliteDynamicDeliveryLedger(store.path)
    sent = AsyncMock()

    def register(*args: Any) -> None:
        ledger.prepare(*args)

    service.register_delivery = register
    monitor = BiliEditMonitor(service, store, sent, AsyncMock(), clock=lambda: now)
    assert store.pending(clock=now) == []
    monitor.observe(item("first online baseline"), now, UID)
    assert store.pending(clock=now) == []
    monitor.observe(item("new revision"), now, UID)
    # Projection does not need a still-retained row in the history UI store.
    await monitor.flush()
    await drain(owner)
    assert sent.await_count == 1
    assert store.pending(clock=now) == []
    await monitor.flush()
    assert sent.await_count == 1
    entry = ledger.queue_entry("123456:edit:1")
    assert entry["item"]["id_str"] == "123456"


@pytest.mark.asyncio
async def test_review_budget_concurrency_and_boost_does_not_review(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    service = build_test_bilibili_service(tmp_path)
    service.targets = cast("Any", Targets())
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    for index in range(15):
        data = item()
        data["id_str"] = str(500 + index)
        save(service, data, now)
    monitor = BiliEditMonitor(
        service, store, AsyncMock(), AsyncMock(), clock=lambda: now
    )
    active = peak = calls = 0

    async def fetch(_cookie: str, source_id: str) -> BiliFeedResponse:
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        data = item()
        data["id_str"] = source_id
        return BiliFeedResponse(200, {"code": 0, "data": {"item": data}})

    service.fetch_detail = fetch
    await monitor.tick(set(), review=False)
    assert calls == 0
    await monitor.tick(set(), review=True)
    assert calls == DETAIL_BUDGET
    assert peak == CONCURRENCY
    await monitor.tick(set(), review=True)
    assert calls == DETAIL_BUDGET


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [AUTH_BAD, 1])
async def test_failed_detail_never_advances_revision(tmp_path: Path, code: int) -> None:
    now = int(time.time())
    service = build_test_bilibili_service(tmp_path)
    service.targets = cast("Any", Targets())
    save(service, item(), now)
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    notice = AsyncMock()
    monitor = BiliEditMonitor(service, store, AsyncMock(), notice, clock=lambda: now)
    service.fetch_detail = AsyncMock(return_value=BiliFeedResponse(200, {"code": code}))
    await monitor.tick(set(), review=True)
    assert store.pending(clock=now) == []
    assert notice.await_count == (1 if code == AUTH_BAD else 0)


@pytest.mark.asyncio
async def test_restart_after_registration_before_outbox_ack_is_idempotent(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    service = build_test_bilibili_service(tmp_path)
    service.targets = cast("Any", Targets())
    owner = TaskOwner()
    service.spawn = owner.create
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    ledger = SqliteDynamicDeliveryLedger(store.path)
    store.observe(item(), now, UID, clock=now)
    store.observe(item("new"), now, UID, clock=now)
    sent = AsyncMock()

    def interrupted(*args: Any) -> None:
        ledger.prepare(*args)
        raise RuntimeError

    service.register_delivery = interrupted
    monitor = BiliEditMonitor(service, store, sent, AsyncMock(), clock=lambda: now)
    with pytest.raises(RuntimeError):
        await monitor.flush()
    assert len(store.pending(clock=now)) == 1
    assert sent.await_count == 0

    def register(*args: Any) -> None:
        ledger.prepare(*args)

    service.register_delivery = register
    restarted = BiliEditMonitor(
        service,
        SqliteBiliRevisionStore(store.path),
        sent,
        AsyncMock(),
        clock=lambda: now,
    )
    await restarted.flush()
    await drain(owner)
    assert store.pending(clock=now) == []
    assert sent.await_count == 1
    assert ledger.queue_entry("123456:edit:1")["item"]["id_str"] == "123456"
