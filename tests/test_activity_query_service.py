from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pytest import MonkeyPatch

from ironsbot.services.activity import query
from ironsbot.services.activity.models import ActivityInfo, ActivityInfoCache

ACTIVITY_ID_ONE = 1
ACTIVITY_ID_TWO = 2


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _activity(
    activity_id: int = ACTIVITY_ID_ONE,
    *,
    name: str = "银河斗技场",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ActivityInfo:
    return ActivityInfo(
        activity_id=activity_id,
        name=name,
        start_time=start_time or dt(2026, 6, 1, 10),
        end_time=end_time or dt(2026, 6, 12, 10),
        sort_order=activity_id,
    )


def _empty_rows() -> list[Mapping[str, Any]]:
    return []


def _first_rows() -> list[Mapping[str, Any]]:
    return [{"id": ACTIVITY_ID_ONE}]


def _second_rows() -> list[Mapping[str, Any]]:
    return [{"id": ACTIVITY_ID_TWO}]


def test_active_activity_infos_reuses_cache_and_filters_against_now(
    monkeypatch: MonkeyPatch,
) -> None:
    cache = ActivityInfoCache()
    build_calls: list[list[Mapping[str, Any]]] = []

    def fake_build_active_activity_infos(
        rows: Iterable[Mapping[str, Any]],
        _now: datetime,
    ) -> list[ActivityInfo]:
        build_calls.append(list(rows))
        return [_activity()]

    monkeypatch.setattr(
        query,
        "build_active_activity_infos",
        fake_build_active_activity_infos,
    )
    source = query.ActivityQuerySource(
        cache=cache,
        load_rows=_first_rows,
        cache_ttl=timedelta(days=2),
        soon_ending_threshold=timedelta(days=7),
    )

    first = query.active_activity_infos(
        source,
        dt(2026, 6, 11, 10),
    )
    second = query.active_activity_infos(
        query.ActivityQuerySource(
            cache=cache,
            load_rows=_second_rows,
            cache_ttl=timedelta(days=2),
            soon_ending_threshold=timedelta(days=7),
        ),
        dt(2026, 6, 12, 11),
    )

    assert [activity.activity_id for activity in first] == [ACTIVITY_ID_ONE]
    assert second == []
    assert build_calls == [[{"id": ACTIVITY_ID_ONE}]]


def test_build_activity_query_message_renders_current_activity(
    monkeypatch: MonkeyPatch,
) -> None:
    cache = ActivityInfoCache()

    def fake_build_active_activity_infos(
        _rows: Iterable[Mapping[str, Any]],
        _now: datetime,
    ) -> list[ActivityInfo]:
        return [
            _activity(ACTIVITY_ID_ONE, name="银河斗技场"),
            _activity(ACTIVITY_ID_TWO, name="审判天使"),
        ]

    monkeypatch.setattr(
        query,
        "build_active_activity_infos",
        fake_build_active_activity_infos,
    )
    source = query.ActivityQuerySource(
        cache=cache,
        load_rows=_empty_rows,
        cache_ttl=timedelta(minutes=1),
        soon_ending_threshold=timedelta(days=7),
    )

    message = query.build_activity_query_message(
        source,
        dt(2026, 6, 11, 10),
        limit=1,
    )

    assert "📅【当前活动】" in message
    assert "1. 银河斗技场：06-01 10:00 ~ 06-12 10:00 | 剩余：1天" in message
    assert "...还有 1 个活动未显示" in message


def test_build_activity_query_message_handles_empty_soon_ending_list(
    monkeypatch: MonkeyPatch,
) -> None:
    cache = ActivityInfoCache()

    def fake_build_active_activity_infos(
        _rows: Iterable[Mapping[str, Any]],
        _now: datetime,
    ) -> list[ActivityInfo]:
        return []

    monkeypatch.setattr(
        query,
        "build_active_activity_infos",
        fake_build_active_activity_infos,
    )
    source = query.ActivityQuerySource(
        cache=cache,
        load_rows=_empty_rows,
        cache_ttl=timedelta(minutes=1),
        soon_ending_threshold=timedelta(days=7),
    )

    message = query.build_activity_query_message(
        source,
        dt(2026, 6, 11, 10),
        soon_only=True,
    )

    assert message == query.EMPTY_SOON_ENDING_ACTIVITY_MESSAGE
