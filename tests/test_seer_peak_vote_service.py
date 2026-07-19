from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from seerapi_models import PeakPoolVoteORM

from ironsbot.core import time
from ironsbot.services.seer import peak

EXPECTED_LOCAL_HOUR = 10


def _naive_datetime(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(
        year,
        month,
        day,
        hour,
        tzinfo=time.TZ_CN,
    ).replace(tzinfo=None)


def _vote(*, vote_id: int, start_time: datetime) -> PeakPoolVoteORM:
    return cast(
        "PeakPoolVoteORM",
        SimpleNamespace(
            id=vote_id,
            start_time=start_time,
            end_time=start_time,
            count=2,
            subkey=vote_id,
        ),
    )


def test_peak_vote_time_treats_naive_database_value_as_china_time() -> None:
    value = _naive_datetime(2026, 7, 16, EXPECTED_LOCAL_HOUR)

    normalized = peak.normalize_peak_vote_time(value)

    assert normalized.tzinfo == time.TZ_CN
    assert normalized.hour == EXPECTED_LOCAL_HOUR


def test_peak_vote_time_converts_aware_value_to_china_time() -> None:
    value = datetime(2026, 7, 16, 2, 0, tzinfo=timezone.utc)

    normalized = peak.normalize_peak_vote_time(value)

    assert normalized.tzinfo == time.TZ_CN
    assert normalized.hour == EXPECTED_LOCAL_HOUR


def test_sort_peak_vote_accepts_naive_database_times(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peak.time,
        "now",
        lambda *, tz: datetime(2026, 7, 16, 12, 0, tzinfo=tz),
    )
    earlier = _vote(vote_id=1, start_time=_naive_datetime(2026, 7, 15, 12))
    nearer = _vote(vote_id=2, start_time=_naive_datetime(2026, 7, 16, 13))

    result = peak.sort_peak_pool_votes_by_time([earlier, nearer])

    assert [vote.id for vote in result] == [2, 1]
