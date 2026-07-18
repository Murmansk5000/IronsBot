import asyncio
from typing import cast

from pytest import MonkeyPatch

from ironsbot.config.models.seer import RankPageRefreshConfig
from ironsbot.integrations.headless_seer.activity import (
    format_recent_headless_operation,
    headless_operation,
    reset_headless_operation_state,
)
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.services.seer import rank_page_refresh
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_page_refresh_models import RankPageRefreshTarget


def test_headless_operation_context_keeps_recent_operation() -> None:
    reset_headless_operation_state()

    with headless_operation(
        "后台刷榜缓存",
        "群星牌 1-100名",
        source="后台刷榜缓存",
        background=True,
    ):
        assert (
            format_recent_headless_operation()
            == "后台刷榜缓存：群星牌 1-100名（后台操作）"
        )

    assert (
        format_recent_headless_operation()
        == "后台刷榜缓存：群星牌 1-100名（后台操作）"
    )
    reset_headless_operation_state()
    assert format_recent_headless_operation() == ""


def test_headless_disconnect_notice_includes_recent_operation() -> None:
    async def run() -> None:
        reset_headless_operation_state()
        notices: list[tuple[bool, str, str, int | None]] = []

        async def notifier(
            *,
            connected: bool,
            reason: str,
            source: str,
            user_id: int | None,
        ) -> None:
            notices.append((connected, reason, source, user_id))

        game = SeerGame(
            123456,
            "password",
            login_server_url="https://example.invalid/unity-ip.txt",
            state_notifier=notifier,
        )

        with headless_operation(
            "后台刷榜缓存",
            "图鉴积分 101-200名",
            source="后台刷榜缓存",
            background=True,
        ):
            await game._handle_disconnect()

        assert notices == [
            (
                False,
                (
                    "连接已断开\n"
                    "疑似触发操作：后台刷榜缓存：图鉴积分 101-200名（后台操作）"
                ),
                "无头连接",
                123456,
            )
        ]

    asyncio.run(run())


def test_intentional_logout_does_not_notify_or_reconnect() -> None:
    async def run() -> None:
        notices: list[tuple[bool, str, str, int | None]] = []

        async def notifier(
            *,
            connected: bool,
            reason: str,
            source: str,
            user_id: int | None,
        ) -> None:
            notices.append((connected, reason, source, user_id))

        game = SeerGame(
            123456,
            "password",
            login_server_url="https://example.invalid/unity-ip.txt",
            reconnect_retries=-1,
            state_notifier=notifier,
        )

        game.logout()
        await game._handle_disconnect()

        assert notices == []
        assert game._reconnect_task is None

    asyncio.run(run())


def test_rank_page_refresh_enters_backoff_after_connection_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    async def run() -> None:
        target = RankPageRefreshTarget(
            rank_key="群星牌",
            spec=GlobalRankSpec("群星之巅榜", key=201, sub_key=0, unit="分"),
            reason="缺失",
            start_rank=1,
            end_rank=100,
            raw_start=0,
            raw_end=99,
        )

        async def fail_fetch(*_args: object, **_kwargs: object) -> list[object]:
            raise TimeoutError

        monkeypatch.setattr(
            rank_page_refresh,
            "get_rank_page_refresh_config",
            lambda: RankPageRefreshConfig(
                pages_per_run=1,
                pages_per_run_min=1,
            ),
        )
        monkeypatch.setattr(
            rank_page_refresh,
            "preview_rank_page_refresh_targets",
            lambda _rank_keys=None: [target],
        )
        monkeypatch.setattr(rank_page_refresh, "fetch_daily_rank_page", fail_fetch)
        rank_page_refresh._rank_page_refresh_state.backoff_until = 0
        game = cast("SeerGame", object())

        result = await rank_page_refresh.refresh_rank_page_cache(game)
        assert result.failed == 1
        assert rank_page_refresh._rank_page_refresh_backoff_remaining() > 0

        skipped = await rank_page_refresh.refresh_rank_page_cache(game)
        assert skipped.total == 0

    asyncio.run(run())
