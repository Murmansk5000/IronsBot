from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.query_result import QueryReply

AT = 1_800_000_000.0


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> tuple[PlayerDetailService, list[float]]:
    clocks = [AT, 100.0]
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.now",
        lambda: datetime.fromtimestamp(clocks[0], tz=timezone.utc),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.monotonic", lambda: clocks[1]
    )
    config = SeerConfig()
    config.player.background_refresh.cache_ttl_seconds = 300
    service = PlayerDetailService(
        config, cast("Any", Mock()), cast("Any", Mock()), Mock()
    )
    return service, clocks


@pytest.mark.parametrize(
    "stamp", [None, AT + 1, AT - 300, AT - 301, float("nan"), float("inf")]
)
def test_unusable_observation_not_admitted(
    cache: tuple[PlayerDetailService, list[float]], stamp: float | None
) -> None:
    service, _ = cache
    service._store_reply(123456, "peak", QueryReply(text="data", fetched_at=stamp))
    assert service._cached_reply(123456, "peak") is None


def test_delayed_and_repeated_insertion_cannot_renew_age(
    cache: tuple[PlayerDetailService, list[float]],
) -> None:
    service, clocks = cache
    reply = QueryReply(text="data", fetched_at=AT - 250)
    service._store_reply(123456, "peak", reply)
    clocks[0] += 49
    clocks[1] += 49
    assert service._cached_reply(123456, "peak") is reply
    service._store_reply(123456, "peak", reply)
    clocks[0] += 1
    clocks[1] += 1
    assert service._cached_reply(123456, "peak") is None


@pytest.mark.parametrize("clock_index", [0, 1])
def test_either_clock_can_expire_cache(
    cache: tuple[PlayerDetailService, list[float]], clock_index: int
) -> None:
    service, clocks = cache
    service._store_reply(123456, "collection", QueryReply(fetched_at=AT))
    clocks[clock_index] += 300
    assert service._cached_reply(123456, "collection") is None


def test_partial_does_not_replace_valid_complete(
    cache: tuple[PlayerDetailService, list[float]],
) -> None:
    service, _ = cache
    complete = QueryReply(fetched_at=AT)
    service._store_reply(123456, "autocard", complete)
    service._store_reply(123456, "autocard", QueryReply(fetched_at=AT, complete=False))
    assert service._cached_reply(123456, "autocard") is complete
