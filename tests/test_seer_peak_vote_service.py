from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch

from ironsbot.core import time
from ironsbot.integrations.seer_data.published_time import local_published_datetime
from ironsbot.services.seer import peak

EXPECTED_LOCAL_HOUR = 10


def _naive_datetime(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).replace(tzinfo=None)


def _vote(*, vote_id: int, start_time: datetime) -> peak.PeakVoteSnapshot:
    return peak.PeakVoteSnapshot(
        id=vote_id,
        start_time=start_time,
        end_time=start_time,
        count=2,
        subkey=vote_id,
        pets=(),
    )


def test_peak_vote_time_treats_naive_database_value_as_utc() -> None:
    value = _naive_datetime(2026, 7, 16, 2)

    normalized = peak.normalize_peak_vote_time(value)

    assert normalized.tzinfo == time.TZ_CN
    assert normalized.hour == EXPECTED_LOCAL_HOUR


def test_peak_vote_time_converts_aware_value_to_china_time() -> None:
    value = datetime(2026, 7, 16, 2, 0, tzinfo=timezone.utc)

    normalized = peak.normalize_peak_vote_time(value)

    assert normalized.tzinfo == time.TZ_CN
    assert normalized.hour == EXPECTED_LOCAL_HOUR


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(
            datetime.fromisoformat("2026-07-16T02:15:30-05:00"),
            "2026-07-16T15:15:30+08:00",
            id="non-utc-offset",
        ),
        pytest.param(
            datetime(2026, 7, 16, 10, 15, 30, tzinfo=time.TZ_CN),
            "2026-07-16T10:15:30+08:00",
            id="already-beijing",
        ),
        pytest.param(
            _naive_datetime(2026, 12, 31, 16),
            "2027-01-01T00:00:00+08:00",
            id="naive-cross-year",
        ),
        pytest.param(
            datetime.fromisoformat("2026-10-01T16:00:00+00:00"),
            "2026-10-02T00:00:00+08:00",
            id="utc-cross-day",
        ),
        pytest.param(
            datetime.fromisoformat("2026-10-02T01:00:00+14:00"),
            "2026-10-01T19:00:00+08:00",
            id="offset-previous-day",
        ),
    ],
)
@pytest.mark.parametrize(
    "normalize", [peak.normalize_peak_vote_time, local_published_datetime]
)
def test_peak_and_published_time_share_beijing_conversion(
    normalize: Callable[[datetime], datetime], value: datetime, expected: str
) -> None:
    normalized = normalize(value)
    assert normalized.tzinfo == time.TZ_CN
    assert normalized.isoformat() == expected
    assert normalize(normalized).isoformat() == expected


def test_sort_peak_vote_accepts_naive_database_times(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peak.time,
        "now",
        lambda *, tz: datetime(2026, 7, 16, 12, 0, tzinfo=tz),
    )
    earlier = _vote(vote_id=1, start_time=_naive_datetime(2026, 7, 15, 4))
    nearer = _vote(vote_id=2, start_time=_naive_datetime(2026, 7, 16, 5))

    result = peak.sort_peak_pool_votes_by_time([earlier, nearer])

    assert [vote.id for vote in result] == [2, 1]
