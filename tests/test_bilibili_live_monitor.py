from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage, SendResult
from ironsbot.core.time import TZ_CN
from ironsbot.integrations.http.bilibili_live import fetch_live_status
from ironsbot.integrations.storage.bilibili_live import SqliteBiliLiveStore
from ironsbot.integrations.storage.proactive_tasks import SqliteProactiveTasks
from ironsbot.services.bilibili.live import BiliLiveMonitor
from ironsbot.services.bilibili.live_models import (
    LiveObservation,
    LiveStatusUnavailableError,
)
from ironsbot.services.bilibili.live_preview import (
    LIVE_ALL_SUBSCRIPTION,
    LIVE_REMINDER_PREFERENCE,
    live_subscription_key,
)
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent, StoredDelivery
from tests.test_bilibili_category_subscriptions import _service
from tests.test_bilibili_live_preview import dynamic
from tests.test_proactive_delivery import FakeFeatures, FakeMessenger, _delivery

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.bilibili.service import BilibiliService

UID = 912345678
START = datetime(2030, 11, 14, 19, tzinfo=TZ_CN).timestamp()
TWO_NOTICES = 2


def _monitor(
    path: Path,
) -> tuple[BiliLiveMonitor, list[float], AsyncMock, FakeMessenger]:
    targets, conversation = _service(path)
    targets.preferences.set_category_muted(
        conversation, UID, LIVE_REMINDER_PREFERENCE, muted=False
    )
    service = cast(
        "BilibiliService",
        SimpleNamespace(
            targets=targets,
            config=targets.config,
            history=SimpleNamespace(list=lambda **_kwargs: []),
        ),
    )
    delivery, messenger, _ = _delivery(features=cast("FakeFeatures", targets.features))
    delivery = replace(delivery, outbox=SqliteProactiveTasks(path / "outbox.sqlite"))
    clock = [START - 600]
    fetch = AsyncMock(
        return_value={
            UID: LiveObservation(
                UID, 700002, live=False, live_time=0, title="旧标题", name="虚构账号"
            )
        }
    )
    monitor = BiliLiveMonitor(
        service,
        SqliteBiliLiveStore(path / "live.sqlite"),
        fetch,
        delivery,
        clock=lambda: clock[0],
    )
    return monitor, clock, fetch, messenger


def _preview(source: str = "one", text: str = "11月14日19:00开启直播") -> dict:
    return dynamic(text, uid=UID, source=source)


@pytest.mark.asyncio
async def test_preview_before_start_end_and_repeated_sources(tmp_path: Path) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    monitor.ingest(_preview())
    monitor.ingest(_preview("two", "本周四晚19:00开启直播"))
    await monitor.tick()
    assert len(messenger.calls) == 1
    assert len(monitor.store.account(UID).schedules) == 1
    clock[0] = START
    fetch.return_value = {
        UID: LiveObservation(
            UID,
            700002,
            live=True,
            live_time=int(START),
            title="新直播标题",
            name="虚构账号",
        )
    }
    await asyncio.gather(monitor.tick(), monitor.tick())
    assert len(messenger.calls) == TWO_NOTICES
    account = monitor.store.account(UID)
    assert account.status == 1
    monitor = replace(monitor, _lock=asyncio.Lock(), _bootstrapped=False)
    await monitor.tick(startup=True)
    assert len(messenger.calls) == TWO_NOTICES
    fetch.return_value = {
        UID: LiveObservation(
            UID, 700002, live=False, live_time=0, title="旧标题", name="虚构账号"
        )
    }
    clock[0] += 60
    await monitor.tick()
    assert monitor.store.account(UID).status == 1
    clock[0] += 60
    await monitor.tick()
    assert monitor.store.account(UID).status == 0
    assert monitor.store.account(UID).schedules[0].ended
    clock[0] += 60
    before = fetch.await_count
    await monitor.tick()
    assert fetch.await_count == before


@pytest.mark.asyncio
async def test_self_forward_shares_schedule_and_already_sent_notices(
    tmp_path: Path,
) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    original = _preview()
    monitor.ingest(original)
    await monitor.tick()
    assert len(messenger.calls) == 1
    forwarded = dynamic(
        "今晚19点，官方直播间准时开播！",
        uid=UID,
        source="self-forward",
        published="2030-11-14T12:00:00+08:00",
    )
    forwarded["type"] = "DYNAMIC_TYPE_FORWARD"
    forwarded["orig"] = original
    monitor.ingest(forwarded)
    account = monitor.store.account(UID)
    assert len(account.schedules) == 1
    assert set(account.schedules[0].sources) == {"one", "self-forward"}
    await monitor.tick()
    assert len(messenger.calls) == 1
    clock[0] = START
    fetch.return_value = {
        UID: LiveObservation(
            UID,
            700002,
            live=True,
            live_time=int(START),
            title="直播中",
            name="虚构账号",
        )
    }
    await monitor.tick()
    assert len(messenger.calls) == TWO_NOTICES
    monitor.ingest(forwarded)
    await monitor.tick()
    assert len(messenger.calls) == TWO_NOTICES


@pytest.mark.asyncio
async def test_no_preview_uses_only_shared_due_and_first_live_is_baseline(
    tmp_path: Path,
) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    fetch.return_value = {
        UID: LiveObservation(
            UID,
            700002,
            live=True,
            live_time=int(START - 300),
            title="直播中",
            name="虚构账号",
        )
    }
    await monitor.tick()
    assert not messenger.calls
    assert monitor.store.account(UID).status == 1
    clock[0] += 60
    await monitor.tick()
    assert not messenger.calls


@pytest.mark.asyncio
async def test_offline_account_waits_for_dynamic_tick(tmp_path: Path) -> None:
    monitor, clock, fetch, _ = _monitor(tmp_path)
    await monitor.tick()
    clock[0] += 60
    await monitor.tick()
    assert fetch.await_count == 1
    await monitor.tick(shared_due=True)
    assert fetch.await_count == TWO_NOTICES


@pytest.mark.asyncio
async def test_no_start_window_ends_ten_minutes_late(tmp_path: Path) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    monitor.ingest(_preview())
    await monitor.tick()
    clock[0] = START + 600
    await monitor.tick()
    before = fetch.await_count
    clock[0] += 60
    await monitor.tick()
    assert fetch.await_count == before
    assert len(messenger.calls) == 1


@pytest.mark.asyncio
async def test_failure_is_not_offline_and_backoff_survives_restart(
    tmp_path: Path,
) -> None:
    monitor, clock, fetch, _ = _monitor(tmp_path)
    await monitor.tick()
    clock[0] += 60
    fetch.side_effect = LiveStatusUnavailableError("synthetic")
    await monitor.tick(shared_due=True)
    assert monitor.store.account(UID).status == 0
    assert monitor.store.account(UID).retry_after > clock[0]
    monitor = replace(monitor, _lock=asyncio.Lock(), _bootstrapped=False)
    clock[0] += 10
    await monitor.tick(shared_due=True)
    assert fetch.await_count == TWO_NOTICES


@pytest.mark.asyncio
async def test_cancel_and_global_disable_stop_work_without_mutating_account_choice(
    tmp_path: Path,
) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    conversation = next(iter(monitor.service.targets.push_group_rules()))
    monitor.ingest(_preview())
    monitor.service.targets.unsubscribe_store.unsubscribe(
        conversation, LIVE_ALL_SUBSCRIPTION, "bili_push"
    )
    await monitor.tick()
    assert not fetch.await_count
    assert not messenger.calls
    assert monitor.service.targets.live_enabled(conversation, UID, include_global=False)
    monitor.service.targets.unsubscribe_store.restore(
        conversation, LIVE_ALL_SUBSCRIPTION
    )
    monitor.ingest(
        dynamic(
            "取消直播", uid=UID, source="cancel", published="2030-11-12T10:00:00+08:00"
        )
    )
    clock[0] += 60
    await monitor.tick(shared_due=True)
    assert not messenger.calls
    assert monitor.store.account(UID).schedules[0].ended


@pytest.mark.asyncio
async def test_outbox_ready_rechecks_subscription_and_fresh_status(
    tmp_path: Path,
) -> None:
    monitor, clock, fetch, _ = _monitor(tmp_path)
    monitor.ingest(_preview())
    await monitor.tick()
    account = monitor.store.account(UID)
    notice = monitor.store.notice(f"live:{UID}:{account.schedules[0].key}:before")
    assert notice is not None
    task = StoredDelivery(
        "fake",
        notice.targets[0],
        OutboundMessage.from_text("synthetic"),
        DeliveryIntent(
            notice.key,
            notice.expires_at,
            source_platform="bilibili_live",
            source_id=notice.key,
        ),
        "test",
        live_subscription_key(UID),
        3,
        (1,),
    )
    assert await monitor.ready(task) is True
    clock[0] += 60
    fetch.side_effect = LiveStatusUnavailableError("synthetic")
    assert await monitor.ready(task) is None
    monitor.service.targets.preferences.set_category_muted(
        task.conversation, UID, LIVE_REMINDER_PREFERENCE, muted=True
    )
    assert await monitor.ready(task) is False


@pytest.mark.asyncio
async def test_status_adapter_validates_identity_and_keeps_unknown_missing() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get_list("uids[]") == [str(UID), "700003"]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    str(UID): {
                        "uid": UID,
                        "room_id": 700002,
                        "live_status": 0,
                        "live_time": 0,
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await fetch_live_status(client, [UID, 700003])
    assert result.keys() == {UID}
    assert not result[UID].live


@pytest.mark.asyncio
async def test_reschedule_replans_only_proven_unsent_pre_notice(tmp_path: Path) -> None:
    monitor, clock, fetch, messenger = _monitor(tmp_path)
    monitor.delivery = replace(
        monitor.delivery, policy=replace(monitor.delivery.policy, max_attempts=1)
    )
    messenger.scripted_results = [
        SendResult(
            delivered=False,
            attempted=False,
            error_code="synthetic_offline",
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
        )
    ]
    monitor.ingest(_preview())
    await monitor.tick()
    assert len(messenger.calls) == 1
    monitor.ingest(
        dynamic(
            "直播原定11月14日19:00，改为11月15日20:00开播",
            uid=UID,
            published="2030-11-14T18:51:00+08:00",
            source="reschedule",
        )
    )
    schedule = monitor.store.account(UID).schedules[0]
    assert schedule.starts_at == datetime(2030, 11, 15, 20, tzinfo=TZ_CN).timestamp()
    assert not monitor.store.notices(clock[0])
    clock[0] = schedule.starts_at - 600
    await monitor.tick()
    assert fetch.await_count == TWO_NOTICES
    assert len(messenger.calls) == TWO_NOTICES


@pytest.mark.asyncio
async def test_successful_pre_notice_is_not_repeated_after_reschedule(
    tmp_path: Path,
) -> None:
    monitor, clock, _, messenger = _monitor(tmp_path)
    monitor.ingest(_preview())
    await monitor.tick()
    monitor.ingest(
        dynamic(
            "直播改为11月15日20:00开播",
            uid=UID,
            published="2030-11-14T18:51:00+08:00",
            source="reschedule",
        )
    )
    clock[0] = monitor.store.account(UID).schedules[0].starts_at - 600
    await monitor.tick()
    assert len(messenger.calls) == 1


@pytest.mark.asyncio
async def test_uncertain_receipt_is_not_replayed_after_crash(tmp_path: Path) -> None:
    monitor, _, _, messenger = _monitor(tmp_path)
    messenger.scripted_results = [
        SendResult(
            delivered=False,
            error_code="synthetic_uncertain",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )
    ]
    monitor.ingest(_preview())
    await monitor.tick()
    await replace(monitor, _bootstrapped=False, _lock=asyncio.Lock()).tick()
    assert len(messenger.calls) == 1


def test_edited_source_replans_same_event_and_ambiguous_reschedule_does_not(
    tmp_path: Path,
) -> None:
    monitor, _, _, _ = _monitor(tmp_path)
    monitor.ingest(_preview())
    original = monitor.store.account(UID).schedules[0].key
    monitor.ingest(_preview(text="11月15日20:00开启直播"))
    assert monitor.store.account(UID).schedules[0].key == original
    monitor.ingest(_preview("second-event", "11月16日20:00开启直播"))
    monitor.ingest(
        dynamic(
            "直播改为11月17日20:00开播",
            uid=UID,
            source="ambiguous",
            published="2030-11-12T10:00:00+08:00",
        )
    )
    assert len(monitor.store.account(UID).schedules) == TWO_NOTICES


def test_cancel_without_time_ignores_expired_historical_previews(
    tmp_path: Path,
) -> None:
    monitor, _, _, _ = _monitor(tmp_path)
    monitor.ingest(_preview("old", "11月12日19:00开启直播"))
    monitor.ingest(_preview())
    monitor.ingest(
        dynamic(
            "取消今晚的直播",
            uid=UID,
            source="cancel",
            published="2030-11-14T18:49:00+08:00",
        )
    )
    assert monitor.store.account(UID).schedules[-1].ended
