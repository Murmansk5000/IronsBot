import asyncio
from contextlib import nullcontext
from time import monotonic
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
from ironsbot.services.seer.player_service import PlayerService
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerBaseSnapshot,
    _BackgroundRefresh,
)
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank_constants import (
    BOOK_RANK_KEY,
    STANDARD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_player_scheduler import (
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakFetchResult,
    UnityPeakInfo,
)

PLAYER_ID = 712345678


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["collection", "peak", "autocard"])
@pytest.mark.parametrize("route", ["foreground", "background"])
@pytest.mark.parametrize("interruption", ["deadline", "cancel"])
async def test_detail_deadline_keeps_result_when_sample_stage_runs_out(  # noqa: C901, PLR0915
    monkeypatch: pytest.MonkeyPatch,
    kind: Any,
    route: str,
    interruption: str,
) -> None:
    config = SeerConfig()
    config.player.detail_timeout_seconds = 0.3
    config.rank.player_lookup.total_timeout_seconds = 0.28
    config.rank.player_lookup.page_timeout_seconds = 0.04
    sample_started = asyncio.Event()
    sample_drained = asyncio.Event()
    pages_drained: list[str] = []

    async def find_rank(_game: Any, **kwargs: Any) -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None

        async def page() -> None:
            if kwargs.get("key") in {BOOK_RANK_KEY, STANDARD_PEAK_USER_RANK_KEY}:
                try:
                    await asyncio.sleep(0.2)
                finally:
                    pages_drained.append("page")

        await scheduler.fetch_page("rank", page)
        return RankLookupResult(
            title=kwargs.get("title", "精灵图鉴"),
            score_name=kwargs.get("score_name", "精灵"),
            rank=4,
            score=kwargs.get("target_score") or 1421,
            queried=True,
        )

    async def runner(jobs: Any) -> Any:
        return await run_player_rank_lookup_jobs(jobs, config.rank.player_lookup)

    class Rank:
        def __init__(self) -> None:
            self.config = config.rank

        def current_peak_sub_key(self) -> int:
            return 7

        async def fetch_player_summary(
            self, game: Any, player_id: int, **kwargs: Any
        ) -> Any:
            return await fetch_player_rank_summary(
                game,
                player_id,
                book_breakdown_limit=2000,
                find_rank=find_rank,
                find_pet_kind_rank=find_rank,
                run_lookup_jobs=runner,
                **kwargs,
            )

        async def fetch_peak_summary(
            self, game: Any, player_id: int, **kwargs: Any
        ) -> Any:
            return await fetch_peak_season_rank_summary(
                game,
                player_id,
                current_peak_sub_key=7,
                find_rank=find_rank,
                run_lookup_jobs=runner,
                **kwargs,
            )

        async def fetch_autocard_summary(
            self, *_args: Any, **_kwargs: Any
        ) -> RankLookupResult:
            await asyncio.sleep(0.26)
            pages_drained.append("autocard")
            return RankLookupResult(
                title="群星之巅榜",
                score_name="分",
                rank=4,
                score=1421,
                queried=True,
            )

    async def collection_base(*_args: Any) -> UnityPartOneInfo:
        await asyncio.sleep(0.05)
        return UnityPartOneInfo(pet_kind_num=1326, skin_num=79)

    async def peak_base(*_args: Any, **_kwargs: Any) -> UnityPeakFetchResult:
        await asyncio.sleep(0.05)
        return UnityPeakFetchResult(
            UnityPeakInfo(current_j_rank=3, current_k_rank=3, current_z_score=1421),
            frozenset({"standard", "wild", "expert"}),
        )

    async def sample(**_kwargs: Any) -> None:
        sample_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            sample_drained.set()

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        collection_base,
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        peak_base,
    )
    game = SimpleNamespace(
        user_id=123456,
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext()),
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="known player")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(total_achieve=5760, pet_all_num=1231)
        ),
    )
    details = PlayerDetailService(
        config,
        cast("Any", Rank()),
        cast(
            "Any",
            SimpleNamespace(
                config=SimpleNamespace(enabled=True), upsert_metrics=sample
            ),
        ),
        cast("Any", Mock(side_effect=AssertionError("unexpected background task"))),
    )
    command = PlayerShortcutCommand(kind=kind, player_id=PLAYER_ID)
    if route == "foreground":
        service = object.__new__(PlayerService)
        service._config = config
        service._details = details
        service._headless = cast(
            "Any",
            SimpleNamespace(
                get_game=lambda: game,
                mark_available=AsyncMock(),
            ),
        )
        operation = service._shortcut_live(
            command, PLAYER_ID, conversation=None, anchor_only=False
        )
    else:
        operation = details._run_background_shortcut(
            cast("Any", game),
            command=command,
            player_id=PLAYER_ID,
            conversation=None,
        )
    task = asyncio.create_task(operation)
    if interruption == "cancel":
        await asyncio.wait_for(sample_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sample_drained.is_set()
        assert not details._cached_replies
        return
    reply = await task
    assert pages_drained
    assert sample_started.is_set()
    assert sample_drained.is_set()
    assert "known player" in reply.text
    assert "第4" in reply.text
    assert "样本数据失败：查询超时" in reply.text
    assert not reply.complete
    assert reply.text.splitlines()[1].startswith("获取时间：")
    assert all(item.failure is None for item in reply.rank_lookups)
    assert current_player_rank_page_scheduler() is None


def _service(
    *,
    enabled: bool,
    detail_timeout_seconds: float = 30.0,
) -> PlayerDetailService:
    config = SeerConfig()
    config.player.background_refresh.enabled = enabled
    config.player.background_refresh.cache_ttl_seconds = 300.0
    config.player.detail_timeout_seconds = detail_timeout_seconds

    def spawn(coroutine: Any, *, name: str) -> asyncio.Task[None]:
        return asyncio.create_task(coroutine, name=name)

    return PlayerDetailService(
        cast("Any", config),
        cast("Any", SimpleNamespace(config=config.rank)),
        cast("Any", object()),
        cast("Any", spawn),
    )


def _pending() -> PendingPlayerQuery:
    user_info = SimpleNamespace(nick="snapshot nick")
    more_info = SimpleNamespace(reg_time=1_700_000_000)
    return PendingPlayerQuery(
        player_id=PLAYER_ID,
        user_info=user_info,
        more_info=more_info,
        player_message="基础资料",
        section_plan=PlayerQuerySectionPlan(
            show_local_rank=False,
            has_collection=True,
            needs_peak_section=True,
            has_autocard_rank=True,
            needs_online_info=True,
            local_rank_enabled=False,
        ),
        base_snapshot=PlayerBaseSnapshot(
            player_id=PLAYER_ID,
            user_info=user_info,
            more_info=more_info,
            online_info=None,
            team_name="snapshot team",
        ),
    )


def test_background_refresh_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        called.append(command.kind)
        return QueryReply(text=command.kind)

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )

    async def run() -> None:
        service = _service(enabled=False)
        service.start_background_refresh(cast("Any", object()), _pending())
        await asyncio.sleep(0)

    asyncio.run(run())

    assert called == []


def test_enabled_background_refresh_warms_and_reuses_section_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[PlayerShortcutCommand] = []

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        called.append(command)
        return QueryReply(text=f"{command.kind} reply")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service."
        "_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS",
        0.01,
    )

    async def run() -> None:
        service = _service(enabled=True)
        tracked_conversations: list[ConversationRef | None] = []
        tracked = asyncio.Event()

        def track(*_args: Any, **kwargs: Any) -> nullcontext[None]:
            tracked_conversations.append(kwargs.get("conversation"))
            tracked.set()
            return nullcontext()

        game = cast(
            "Any",
            SimpleNamespace(operations=SimpleNamespace(track=track)),
        )
        conversation = ConversationRef(Platform.ONEBOT, "group", "987654321")
        service.start_background_refresh(
            game,
            _pending(),
            conversation=conversation,
        )
        await asyncio.wait_for(tracked.wait(), timeout=0.1)

        first = await service.shortcut(
            game,
            PlayerShortcutCommand(kind="peak", player_id=PLAYER_ID),
            PLAYER_ID,
        )
        second = await service.shortcut(
            game,
            PlayerShortcutCommand(kind="peak", player_id=PLAYER_ID),
            PLAYER_ID,
        )

        assert first.text == "peak reply"
        assert second.text == "peak reply"
        assert tracked_conversations
        assert set(tracked_conversations) == {conversation}

    asyncio.run(run())

    peak_commands = [command for command in called if command.kind == "peak"]
    assert len(peak_commands) == 1
    assert peak_commands[0].base_snapshot is not None
    assert peak_commands[0].base_snapshot.nick == "snapshot nick"


def test_background_refresh_reports_inflight_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        if command.kind == "collection":
            started.set()
            await release.wait()
        return QueryReply(text=f"{command.kind} reply")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )

    async def run() -> None:
        service = _service(enabled=True)
        game = cast(
            "Any",
            SimpleNamespace(
                operations=SimpleNamespace(
                    track=lambda *_args, **_kwargs: nullcontext()
                )
            ),
        )
        service.start_background_refresh(game, _pending())
        await started.wait()

        assert service.has_inflight_refresh(PLAYER_ID, "collection")

        release.set()
        reply = await service.cached_or_inflight_reply(
            PLAYER_ID,
            "collection",
        )

        assert reply is not None
        assert reply.text == "collection reply"
        assert not service.has_inflight_refresh(PLAYER_ID, "collection")

    asyncio.run(run())


def test_direct_shortcut_bypasses_and_releases_pending_background_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        called.append(command.kind)
        return QueryReply(text="collection reply")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )

    async def run() -> None:
        service = _service(enabled=True)
        future: asyncio.Future[QueryReply | None] = (
            asyncio.get_running_loop().create_future()
        )
        service._background_refreshes[PLAYER_ID] = _BackgroundRefresh(
            replies={"collection": future},
            started_at=monotonic(),
        )

        reply = await asyncio.wait_for(
            service.shortcut(
                cast("Any", object()),
                PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
                PLAYER_ID,
            ),
            timeout=0.1,
        )

        assert future.done()
        assert future.result() is reply
        assert reply.text == "collection reply"

    asyncio.run(run())
    assert called == ["collection"]


def test_player_shortcut_live_prefers_live_data_while_quota_is_available() -> None:
    async def run() -> None:
        reply = QueryReply(text="preheated autocard reply")
        details = SimpleNamespace(shortcut=AsyncMock(return_value=reply))
        game = SimpleNamespace(
            user_id=123456,
            operations=SimpleNamespace(
                track=lambda *_args, **_kwargs: nullcontext(),
            ),
        )
        headless = SimpleNamespace(
            get_game=lambda: game,
            mark_available=AsyncMock(),
        )
        service = PlayerService(
            config=cast(
                "Any",
                SimpleNamespace(
                    player=SimpleNamespace(detail_timeout_seconds=30.0),
                ),
            ),
            headless=cast("Any", headless),
            bindings=cast("Any", object()),
            error_message=cast("Any", object()),
            details=cast("Any", details),
        )

        result = await service._shortcut_live(
            PlayerShortcutCommand(kind="autocard", player_id=PLAYER_ID),
            PLAYER_ID,
            conversation=ConversationRef(Platform.ONEBOT, "group", "987654321"),
            anchor_only=False,
        )

        assert result is reply
        details.shortcut.assert_awaited_once_with(
            game,
            PlayerShortcutCommand(kind="autocard", player_id=PLAYER_ID),
            PLAYER_ID,
            use_cache=False,
            anchor_only=False,
        )

    asyncio.run(run())


def test_background_refresh_expiration_releases_inflight_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service."
        "_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS",
        0.01,
    )
    started = asyncio.Event()

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        if command.kind == "collection":
            started.set()
            await asyncio.Event().wait()
        return QueryReply(text=f"{command.kind} reply")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )

    async def run() -> None:
        service = _service(enabled=True, detail_timeout_seconds=0.01)
        game = cast(
            "Any",
            SimpleNamespace(
                operations=SimpleNamespace(
                    track=lambda *_args, **_kwargs: nullcontext()
                )
            ),
        )
        service.start_background_refresh(game, _pending())
        await started.wait()
        assert service.has_inflight_refresh(PLAYER_ID, "collection")

        await asyncio.sleep(0.03)

        assert not service.has_inflight_refresh(PLAYER_ID, "collection")

    asyncio.run(run())


@pytest.mark.asyncio
async def test_partial_background_reply_is_delivered_but_not_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(enabled=True)
    release = asyncio.Event()
    started = asyncio.Event()
    hold_other_sections = asyncio.Event()
    partial_reply = QueryReply(text="partial", complete=False)

    async def fetch(
        *_args: Any, command: PlayerShortcutCommand, **_kwargs: Any
    ) -> QueryReply:
        if command.kind != "collection":
            await hold_other_sections.wait()
            return QueryReply(text=command.kind)
        started.set()
        await release.wait()
        return partial_reply

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )
    game = SimpleNamespace(
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
    )
    service.start_background_refresh(cast("Any", game), _pending())
    refresh = service._background_refreshes[PLAYER_ID]
    await asyncio.wait_for(started.wait(), timeout=1)
    waiter = asyncio.create_task(
        service.cached_or_inflight_reply(PLAYER_ID, "collection")
    )
    await asyncio.sleep(0)
    release.set()
    try:
        assert await waiter is partial_reply
        assert not service._cached_replies
        assert await service.cached_or_inflight_reply(PLAYER_ID, "collection") is None
        assert service.has_inflight_refresh(PLAYER_ID, "peak")
    finally:
        hold_other_sections.set()
        assert refresh.task is not None
        await refresh.task


@pytest.mark.asyncio
async def test_expired_background_producer_cannot_publish_to_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(enabled=True)
    started = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    cancelled = asyncio.Event()
    generation = 0

    async def fetch(
        *_args: Any, command: PlayerShortcutCommand, **_kwargs: Any
    ) -> QueryReply:
        nonlocal generation
        if command.kind != "collection":
            return QueryReply(text=command.kind)
        current = generation
        generation += 1
        started[current].set()
        try:
            await release[current].wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release[current].wait()
        return QueryReply(text=f"generation {current}")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )
    game = SimpleNamespace(
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
    )
    service.start_background_refresh(cast("Any", game), _pending())
    old = service._background_refreshes[PLAYER_ID]
    await asyncio.wait_for(started[0].wait(), timeout=1)
    service._expire_background_refresh(PLAYER_ID, old)
    service.start_background_refresh(cast("Any", game), _pending())
    new = service._background_refreshes[PLAYER_ID]
    await asyncio.wait_for(started[1].wait(), timeout=1)
    release[0].set()
    assert old.task is not None and new.task is not None
    try:
        await asyncio.gather(old.task, return_exceptions=True)
        assert cancelled.is_set()
        assert service._background_refreshes[PLAYER_ID] is new
        assert not new.replies["collection"].done()
        assert service._cached_reply(PLAYER_ID, "collection") is None
    finally:
        release[1].set()
        await new.task
    assert service._cached_reply(PLAYER_ID, "collection") == QueryReply(
        text="generation 1"
    )


def test_partial_reply_does_not_replace_complete_cache() -> None:
    service = _service(enabled=True)
    complete = QueryReply(text="complete")
    service._store_reply(PLAYER_ID, "collection", complete)
    service._store_reply(
        PLAYER_ID, "collection", QueryReply(text="partial", complete=False)
    )
    assert service._cached_reply(PLAYER_ID, "collection") is complete


@pytest.mark.asyncio
async def test_foreground_result_cannot_fulfill_a_replacement_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(enabled=True)
    loop = asyncio.get_running_loop()
    old = _BackgroundRefresh(
        replies={"collection": loop.create_future()}, started_at=monotonic()
    )
    new = _BackgroundRefresh(
        replies={"collection": loop.create_future()}, started_at=monotonic()
    )
    service._background_refreshes[PLAYER_ID] = old
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(*_args: Any, **_kwargs: Any) -> QueryReply:
        started.set()
        await release.wait()
        return QueryReply(text="old foreground result")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.fetch_player_shortcut_reply",
        fetch,
    )
    task = asyncio.create_task(
        service.shortcut(
            cast("Any", object()),
            PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
            PLAYER_ID,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        service._expire_background_refresh(PLAYER_ID, old)
        assert await old.replies["collection"] is None
        service._background_refreshes[PLAYER_ID] = new
        release.set()
        assert (await task).text == "old foreground result"
        assert not new.replies["collection"].done()
        assert not service._cached_replies
        service._finish_background_refresh(PLAYER_ID, old)
        assert service._background_refreshes[PLAYER_ID] is new
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        service._finish_background_refresh(PLAYER_ID, new)
