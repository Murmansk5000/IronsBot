from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.integrations.headless_seer.packets.user import MoreInfo, UserInfo
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer.player_basic_query import fetch_pending_player_query

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.operations.headless import HeadlessGame

PLAYER_ID = 123456
REG_TIME = 1_270_000_000


class _ProfileCache:
    def __init__(self, reg_time: int | None = None) -> None:
        self.reg_time = reg_time
        self.writes: list[tuple[int, str, int]] = []

    def registration_time(
        self,
        player_id: int,
        *,
        max_age_days: int = 30,
    ) -> int | None:
        del player_id, max_age_days
        return self.reg_time

    def upsert_registration_time(
        self,
        *,
        player_id: int,
        nick: str,
        reg_time: int,
    ) -> None:
        self.writes.append((player_id, nick, reg_time))


class _Game:
    def __init__(
        self,
        *,
        release_fanout: asyncio.Event | None = None,
        fail_more: bool = False,
    ) -> None:
        self.operations = HeadlessOperationTracker()
        self.events: list[str] = []
        self.started: set[str] = set()
        self._release_fanout = release_fanout
        self._fail_more = fail_more

    async def get_user_info(self, player_id: int) -> UserInfo:
        self.events.append("user")
        return UserInfo(
            user_id=player_id,
            nick="tester",
            team_id=9001,
            login_time=1_780_000_000,
            last_offline_time=1_780_000_100,
        )

    async def get_more_user_info(self, player_id: int) -> MoreInfo:
        if self._fail_more:
            message = "registration time cache should skip more info"
            raise AssertionError(message)
        await self._fanout("more")
        return MoreInfo(user_id=player_id, nick="tester", reg_time=REG_TIME)

    async def get_user_online_info(self, player_id: int) -> Any:
        del player_id
        await self._fanout("online")
        return SimpleNamespace(server_id=1701, map_type=0)

    async def get_team_info(self, team_id: int) -> Any:
        del team_id
        await self._fanout("team")
        return SimpleNamespace(name="test team")

    async def _fanout(self, label: str) -> None:
        self.events.append(label)
        self.started.add(label)
        if self._release_fanout is not None:
            await self._release_fanout.wait()


async def _wait_for_labels(actual: set[str], expected: Iterable[str]) -> None:
    expected_set = set(expected)
    for _ in range(1000):
        if expected_set <= actual:
            return
        await asyncio.sleep(0)
    message = f"timed out waiting for fanout: {sorted(expected_set - actual)}"
    raise AssertionError(message)


@pytest.mark.asyncio
async def test_profile_cache_miss_fetches_parallel_fields_and_writes_reg_time() -> None:
    release = asyncio.Event()
    game = _Game(release_fanout=release)
    cache = _ProfileCache()

    task = asyncio.create_task(
        fetch_pending_player_query(
            SeerConfig(),
            PLAYER_ID,
            cast("HeadlessGame", game),
            group_id=100,
            profile_cache=cache,
        )
    )
    await _wait_for_labels(game.started, ("more", "online", "team"))
    assert game.events[0] == "user"
    release.set()
    result = await task

    assert result.more_info.reg_time == REG_TIME
    assert cache.writes == [(PLAYER_ID, "tester", REG_TIME)]
    assert result.base_snapshot is not None
    assert result.base_snapshot.user_info is result.user_info
    assert result.base_snapshot.more_info is result.more_info
    assert result.base_snapshot.team_name == "test team"
    assert "是否在线：在线（服务器：1701，地图类型：0）" in result.player_message
    assert "战队：test team（战队ID：9001，隐藏）" in result.player_message


@pytest.mark.asyncio
async def test_profile_cache_hit_skips_more_info_packet() -> None:
    game = _Game(fail_more=True)
    cache = _ProfileCache(REG_TIME)

    result = await fetch_pending_player_query(
        SeerConfig(),
        PLAYER_ID,
        cast("HeadlessGame", game),
        group_id=None,
        profile_cache=cache,
    )

    assert result.more_info.reg_time == REG_TIME
    assert result.base_snapshot is not None
    assert result.base_snapshot.more_info is result.more_info
    assert cache.writes == []
    assert "more" not in game.events
