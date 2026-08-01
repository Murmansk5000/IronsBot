import asyncio
from contextlib import nullcontext
from time import monotonic
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerDetailService,
    PlayerService,
    _BackgroundRefresh,
)
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply

PLAYER_ID = 105023264


def _service(
    *,
    enabled: bool,
    detail_timeout_seconds: float = 30.0,
) -> PlayerDetailService:
    config = SimpleNamespace(
        player=SimpleNamespace(
            background_refresh=SimpleNamespace(
                enabled=enabled,
                cache_ttl_seconds=300.0,
            ),
            detail_timeout_seconds=detail_timeout_seconds,
        )
    )

    def spawn(coroutine: Any, *, name: str) -> asyncio.Task[None]:
        return asyncio.create_task(coroutine, name=name)

    return PlayerDetailService(
        cast("Any", config),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", spawn),
    )


def _pending() -> PendingPlayerQuery:
    return PendingPlayerQuery(
        player_id=PLAYER_ID,
        user_info=object(),
        more_info=object(),
        player_message="基础资料",
        section_plan=PlayerQuerySectionPlan(
            show_local_rank=False,
            has_collection=True,
            needs_peak_section=True,
            has_autocard_rank=True,
            needs_online_info=True,
            local_rank_enabled=False,
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
        "ironsbot.services.seer.player_service.fetch_player_shortcut_reply",
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
    called: list[str] = []

    async def fetch(
        *_args: Any,
        command: PlayerShortcutCommand,
        **_kwargs: Any,
    ) -> QueryReply:
        called.append(command.kind)
        return QueryReply(text=f"{command.kind} reply")

    monkeypatch.setattr(
        "ironsbot.services.seer.player_service.fetch_player_shortcut_reply",
        fetch,
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_service."
        "_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS",
        0.01,
    )

    async def run() -> None:
        service = _service(enabled=True)
        tracked_groups: list[int | None] = []
        tracked = asyncio.Event()

        def track(*_args: Any, **kwargs: Any) -> nullcontext[None]:
            tracked_groups.append(kwargs.get("group_id"))
            tracked.set()
            return nullcontext()

        game = cast(
            "Any",
            SimpleNamespace(
                operations=SimpleNamespace(track=track)
            ),
        )
        service.start_background_refresh(game, _pending(), group_id=987654321)
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
        assert tracked_groups
        assert set(tracked_groups) == {987654321}

    asyncio.run(run())

    assert called.count("peak") == 1


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
        "ironsbot.services.seer.player_service.fetch_player_shortcut_reply",
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
        reply = await service.shortcut(
            game,
            PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
            PLAYER_ID,
        )

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
        "ironsbot.services.seer.player_service.fetch_player_shortcut_reply",
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
            group_id=987654321,
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
        "ironsbot.services.seer.player_service.fetch_player_shortcut_reply",
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
