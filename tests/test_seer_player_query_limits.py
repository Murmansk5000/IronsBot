from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from ironsbot.core.time import TZ_CN
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.player_query_limits import (
    SqlitePlayerQueryLimitStore,
)
from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerQueryResult,
    PlayerService,
)
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import QueryWorkResult
from ironsbot.services.seer.rank_models import RankLookupCost, RankLookupResult

if TYPE_CHECKING:
    from pathlib import Path

USER_ID = 10001
DEFAULT_PLAYER_ID = 123456
OTHER_PLAYER_ID = 654321
NOW = datetime(2026, 7, 21, 12, tzinfo=TZ_CN)
_LIVE_QUERY_LIMIT = 2


class _Features:
    def __init__(self, *, superuser: bool = False) -> None:
        self._superuser = superuser

    def is_superuser(self, user_id: int) -> bool:
        _ = user_id
        return self._superuser


def _config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "enabled": True,
        "bound_default_daily_limit": 2,
        "other_target_action_daily_limit": 1,
        "unbound_daily_limit": 1,
        "superuser_bypass": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _quota(
    tmp_path: Path,
    bindings: SqlitePlayerBindingStore,
    **config_overrides: object,
) -> PlayerQueryQuotaService:
    return PlayerQueryQuotaService(
        cast("Any", _config(**config_overrides)),
        bindings,
        _Features(),
        SqlitePlayerQueryLimitStore(tmp_path / "limits.sqlite"),
        now=lambda: NOW,
    )


def test_unbound_daily_quota_is_recorded_only_when_consumed(tmp_path: Path) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings, bound_default_daily_limit=10)

    initial = quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    )
    assert initial.allowed
    assert initial.message == ""
    assert quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed

    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed
    denied = quota.check(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="peak",
    )
    assert not denied.allowed
    assert "额度已用完（1 项逻辑操作）" in denied.message
    assert "仍可查看已有缓存" in denied.message
    assert "可从 1 项提升至 10 项" in denied.message
    assert "首次成功查询时可按提示设为默认米米号" in denied.message


def test_unbound_quota_omits_upgrade_hint_when_binding_does_not_increase_limit(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(
        tmp_path,
        bindings,
        unbound_daily_limit=_LIVE_QUERY_LIMIT,
        bound_default_daily_limit=2,
    )
    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed
    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
    ).allowed

    denied = quota.check(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="collection",
    )

    assert not denied.allowed
    assert "首次成功查询时可按提示设为默认米米号" not in denied.message


def test_bound_default_budget_is_shared_by_player_actions(tmp_path: Path) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    bindings.bind(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        player_nick="tester",
        changed_at=NOW,
    )
    quota = _quota(tmp_path, bindings)

    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed
    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="collection",
    ).allowed


def test_other_player_budget_is_shared_across_targets_and_actions(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    bindings.bind(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        player_nick="tester",
        changed_at=NOW,
    )
    quota = _quota(tmp_path, bindings)

    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="peak",
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="peak",
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="collection",
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID + 1,
        action_key="peak",
    ).allowed


def test_superuser_bypasses_persistent_budget(tmp_path: Path) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = PlayerQueryQuotaService(
        cast("Any", _config(unbound_daily_limit=0)),
        bindings,
        _Features(superuser=True),
        SqlitePlayerQueryLimitStore(tmp_path / "limits.sqlite"),
        now=lambda: NOW,
    )

    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed


def test_logical_work_settlement_allows_one_request_to_finish_then_blocks_next(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings, unbound_daily_limit=1)
    work = QueryWorkResult(
        scope="foreground",
        successful_units=frozenset(
            ("peak_base", "rank:peak_standard", "rank:peak_wild", "rank:peak_expert")
        ),
    )

    assert quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
    ).allowed
    assert quota.record_successful_work(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
        units=work.billable_units,
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="collection",
    ).allowed


def test_basic_work_units_are_billed_once(tmp_path: Path) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings, unbound_daily_limit=2)
    work = QueryWorkResult(
        scope="foreground",
        successful_units=frozenset(
            ("profile", "profile_extra", "online_status", "team_info")
        ),
    )
    assert work.billable_units == frozenset(("basic_info",))
    quota.record_successful_work(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
        units=work.billable_units,
    )
    assert quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="collection",
    ).allowed


def test_next_beijing_day_has_a_new_budget(tmp_path: Path) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    current = NOW
    quota = PlayerQueryQuotaService(
        cast("Any", _config()),
        bindings,
        _Features(),
        SqlitePlayerQueryLimitStore(tmp_path / "limits.sqlite"),
        now=lambda: current,
    )

    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
    ).allowed

    current += timedelta(days=1)
    assert quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="peak",
    ).allowed


def test_player_query_consumes_quota_only_after_its_reply_is_returned(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings)
    config = SimpleNamespace(
        player=SimpleNamespace(
            binding=SimpleNamespace(change_cooldown_days=3),
        )
    )
    service = PlayerService(
        cast("Any", config),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", object()),
        quota,
        now=lambda: NOW,
    )

    async def run() -> None:
        async def fail(*_args: Any, **_kwargs: Any) -> PlayerQueryResult:
            return PlayerQueryResult(message="failed")

        service._query = fail  # type: ignore[method-assign]
        failed = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )
        assert failed.message == "failed"
        assert quota.check(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="player",
        ).allowed

        async def succeed(*_args: Any, **_kwargs: Any) -> PlayerQueryResult:
            return PlayerQueryResult(
                pending=PendingPlayerQuery(
                    player_id=DEFAULT_PLAYER_ID,
                    user_info=SimpleNamespace(nick="tester"),
                    more_info=object(),
                    player_message="ok",
                    section_plan=cast("Any", object()),
                )
            )

        service._query = succeed  # type: ignore[method-assign]
        success = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )
        assert success.pending is not None
        assert quota.check(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="player",
        ).allowed

        service.record_returned_query(USER_ID, success.pending)
        assert not quota.check(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="player",
        ).allowed

        service.record_returned_query(USER_ID, success.pending)

    asyncio.run(run())


def test_player_query_prefers_live_until_quota_then_uses_cache(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(
        tmp_path,
        bindings,
        unbound_daily_limit=2,
        bound_default_daily_limit=10,
    )
    config = SimpleNamespace(
        player=SimpleNamespace(
            binding=SimpleNamespace(change_cooldown_days=3),
            background_refresh=SimpleNamespace(cache_ttl_seconds=300.0),
        )
    )
    service = PlayerService(
        cast("Any", config),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", object()),
        quota,
        now=lambda: NOW,
    )
    live_calls = 0

    async def run() -> None:
        async def succeed(*_args: Any, **_kwargs: Any) -> PlayerQueryResult:
            nonlocal live_calls
            live_calls += 1
            return PlayerQueryResult(
                pending=PendingPlayerQuery(
                    player_id=DEFAULT_PLAYER_ID,
                    user_info=SimpleNamespace(nick="tester"),
                    more_info=object(),
                    player_message=f"live-{live_calls}",
                    section_plan=cast("Any", object()),
                )
            )

        service._query = succeed  # type: ignore[method-assign]
        first = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )
        assert first.pending is not None
        service.record_returned_query(USER_ID, first.pending)

        second = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )
        assert second.pending is not None
        assert second.pending.player_message == "live-2"
        service.record_returned_query(USER_ID, second.pending)

        cached = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )
        assert cached.pending is not None
        assert cached.pending.player_message == "live-2"
        assert cached.pending.quota_recorded

    asyncio.run(run())
    assert live_calls == _LIVE_QUERY_LIMIT


def test_player_detail_uses_valid_cache_without_quota_or_live_request(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(
        tmp_path,
        bindings,
        unbound_daily_limit=_LIVE_QUERY_LIMIT,
        bound_default_daily_limit=10,
    )
    latest = QueryReply(text="old-cache")

    class _Details:
        async def cached_or_inflight_reply(self, *_args: object) -> QueryReply:
            return latest

    service = PlayerService(
        cast(
            "Any",
            SimpleNamespace(
                player=SimpleNamespace(binding=SimpleNamespace(change_cooldown_days=3))
            ),
        ),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", _Details()),
        quota,
        now=lambda: NOW,
    )
    live_calls = 0

    async def run() -> None:
        nonlocal latest, live_calls

        async def fetch_live(
            _command: PlayerShortcutCommand,
            _player_id: int,
            *,
            group_id: int | None,
            anchor_only: bool,
        ) -> QueryReply:
            assert group_id is None
            assert not anchor_only
            nonlocal latest, live_calls
            live_calls += 1
            latest = QueryReply(text=f"live-{live_calls}")
            return latest

        service._shortcut_live = fetch_live  # type: ignore[method-assign]
        command = PlayerShortcutCommand(
            kind="collection",
            player_id=DEFAULT_PLAYER_ID,
        )
        assert (await service.shortcut(command, USER_ID)).text == "old-cache"
        assert (await service.shortcut(command, USER_ID)).text == "old-cache"
        assert (await service.shortcut(command, USER_ID)).text == "old-cache"

    asyncio.run(run())
    assert live_calls == 0
    assert quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="collection",
    ).allowed


def test_exhausted_shortcut_returns_valid_detail_cache_without_live_lookup(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings, unbound_daily_limit=1)
    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="player",
    ).allowed

    latest = QueryReply(text="cached reply")

    class _Details:
        async def cached_or_inflight_reply(self, *_args: object) -> QueryReply:
            return latest

    service = PlayerService(
        cast(
            "Any",
            SimpleNamespace(
                player=SimpleNamespace(binding=SimpleNamespace(change_cooldown_days=3))
            ),
        ),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", _Details()),
        quota,
        now=lambda: NOW,
    )
    live_calls = 0

    async def run() -> None:
        async def fetch_live(
            _command: PlayerShortcutCommand,
            _player_id: int,
            *,
            group_id: int | None,
            _anchor_only: bool,
        ) -> QueryReply:
            assert group_id is None
            nonlocal live_calls
            live_calls += 1
            return QueryReply(
                text="fresh lightweight reply",
                rank_lookups=(
                    RankLookupResult(
                        title="图鉴积分",
                        score_name="点",
                        rank=150,
                        score=5000,
                        cost=RankLookupCost(
                            anchor_page_start=100,
                            page_starts=[100],
                            anchor_page_hit=True,
                        ),
                    ),
                ),
            )

        service._shortcut_live = fetch_live  # type: ignore[method-assign]
        reply = await service.shortcut(
            PlayerShortcutCommand(kind="collection", player_id=DEFAULT_PLAYER_ID),
            USER_ID,
        )
        assert reply.text == "cached reply"

    asyncio.run(run())
    assert live_calls == 0
    assert not quota.check(
        qq_user_id=USER_ID,
        player_id=DEFAULT_PLAYER_ID,
        action_key="collection",
    ).allowed


def test_initial_binding_choice_uses_the_default_player_quota(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings)
    assert quota.consume(
        qq_user_id=USER_ID,
        player_id=OTHER_PLAYER_ID,
        action_key="player",
    ).allowed
    config = SimpleNamespace(
        player=SimpleNamespace(
            binding=SimpleNamespace(change_cooldown_days=3),
        )
    )
    service = PlayerService(
        cast("Any", config),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", object()),
        quota,
        now=lambda: NOW,
    )

    async def run() -> None:
        pending = PendingPlayerQuery(
            player_id=DEFAULT_PLAYER_ID,
            user_info=SimpleNamespace(nick="tester"),
            more_info=object(),
            player_message="ok",
            section_plan=cast("Any", object()),
            query_work=QueryWorkResult(
                scope="foreground",
                successful_units=frozenset(("profile", "online_status")),
            ),
        )
        service.save_binding_choice(USER_ID, pending, accepted=True)

        assert bindings.get(USER_ID).player_id == DEFAULT_PLAYER_ID
        assert quota.check(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="player",
        ).allowed

        service.record_returned_query(USER_ID, pending)
        assert quota.consume(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="peak",
        ).allowed
        assert not quota.check(
            qq_user_id=USER_ID,
            player_id=DEFAULT_PLAYER_ID,
            action_key="collection",
        ).allowed

    asyncio.run(run())


def test_player_query_keeps_its_admission_when_it_leaves_the_queue(
    tmp_path: Path,
) -> None:
    bindings = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    quota = _quota(tmp_path, bindings)
    config = SimpleNamespace(
        player=SimpleNamespace(
            binding=SimpleNamespace(change_cooldown_days=3),
        )
    )
    queried = False

    class _Queue:
        async def run(self, operation: Any, **_kwargs: Any) -> PlayerQueryResult:
            quota.consume(
                qq_user_id=USER_ID,
                player_id=DEFAULT_PLAYER_ID,
                action_key="player",
            )
            return await operation()

    service = PlayerService(
        cast("Any", config),
        cast("Any", object()),
        bindings,
        cast("Any", object()),
        cast("Any", object()),
        quota,
        cast("Any", _Queue()),
        now=lambda: NOW,
    )

    async def run() -> None:
        async def succeed(*_args: Any, **_kwargs: Any) -> PlayerQueryResult:
            nonlocal queried
            queried = True
            return PlayerQueryResult(
                pending=PendingPlayerQuery(
                    player_id=DEFAULT_PLAYER_ID,
                    user_info=SimpleNamespace(nick="tester"),
                    more_info=object(),
                    player_message="ok",
                    section_plan=cast("Any", object()),
                )
            )

        service._query = succeed  # type: ignore[method-assign]
        result = await service.query(
            DEFAULT_PLAYER_ID,
            qq_user_id=USER_ID,
            explicit=True,
        )

        assert result.pending is not None
        assert queried

    asyncio.run(run())
