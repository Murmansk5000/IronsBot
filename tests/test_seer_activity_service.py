from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.services.activity.delivery import (
    ActivityReminderDelivery,
    ActivityReminderTargets,
)
from ironsbot.services.activity.models import ActivityInfoCache
from ironsbot.services.activity.service import (
    EMPTY_SOON_ENDING_ACTIVITY_MESSAGE,
    ActivityService,
)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=LOCAL_TZ)


def _row(
    activity_id: int,
    name: str,
    *,
    end_day: int,
) -> Mapping[str, Any]:
    return {
        "id": activity_id,
        "name": name,
        "start_time": "2026-06-01 10:00:00",
        "end_time": f"2026-06-{end_day:02d} 10:00:00",
        "sort_order": activity_id,
    }


def _service(
    rows: list[Mapping[str, Any]],
    *,
    now: datetime,
    cache_ttl: timedelta = timedelta(minutes=1),
    load_rows: Callable[[], list[Mapping[str, Any]]] | None = None,
) -> ActivityService:
    async def broadcast(_delivery: ActivityReminderDelivery) -> bool:
        return True

    return ActivityService(
        config=ActivityConfig(),
        cache=ActivityInfoCache(),
        load_rows=load_rows or (lambda: rows),
        load_notice_text=lambda _now: "",
        cache_ttl=cache_ttl,
        soon_ending_threshold=timedelta(days=7),
        filter_unsent=lambda reminders: reminders,
        mark_sent=lambda _reminders, _sent_at: None,
        preference_values=tuple,
        preference_for_target=lambda _target_type, _target_id: None,
        targets=ActivityReminderTargets,
        broadcast=broadcast,
        now=lambda: now,
    )


def test_active_activity_infos_reuses_cache_and_filters_against_now() -> None:
    calls = 0
    def load_rows() -> list[Mapping[str, Any]]:
        nonlocal calls
        calls += 1
        return [_row(1, "银河斗技场", end_day=12)]

    service = _service(
        [],
        now=dt(11),
        cache_ttl=timedelta(days=2),
        load_rows=load_rows,
    )

    assert [item.activity_id for item in service.active_activity_infos(dt(11))] == [1]
    assert service.active_activity_infos(dt(12, 11)) == []
    assert calls == 1


def test_build_current_message_renders_and_limits_activities() -> None:
    service = _service(
        [
            _row(1, "银河斗技场", end_day=12),
            _row(2, "审判天使", end_day=13),
        ],
        now=dt(11),
    )

    message = service.build_current_message(limit=1)

    assert "📅【当前活动】" in message
    assert "1. 银河斗技场：06-01 10:00 ~ 06-12 10:00 | 剩余：1天" in message
    assert "...还有 1 个活动未显示" in message


def test_build_current_message_handles_empty_soon_ending_list() -> None:
    service = _service([], now=dt(11))

    assert (
        service.build_current_message(soon_only=True)
        == EMPTY_SOON_ENDING_ACTIVITY_MESSAGE
    )
