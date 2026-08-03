import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.seer import RankPageRefreshConfig
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
    semantic_request_scope,
)
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer import rank_page_refresh
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_page_refresh_models import RankPageRefreshTarget

if TYPE_CHECKING:
    from ironsbot.integrations.headless_seer.core.connect import SeerEncryptConnect
    from ironsbot.services.seer.rank import RankService


def test_headless_operation_context_keeps_recent_operation() -> None:
    operations = HeadlessOperationTracker()

    with operations.track(
        "后台刷榜缓存",
        "群星牌 1-100名",
        source="后台刷榜缓存",
        background=True,
    ):
        assert (
            operations.format_recent()
            == "后台刷榜缓存：群星牌 1-100名（后台操作）"
        )

    assert (
        operations.format_recent()
        == "后台刷榜缓存：群星牌 1-100名（后台操作）"
    )
    assert operations.format_recent(now=float("inf")) == ""


def test_headless_operation_context_includes_group_id() -> None:
    operations = HeadlessOperationTracker()

    with operations.track(
        "基础资料",
        "米米号 123456",
        source="米米号查询",
        group_id=987654321,
    ):
        assert operations.format_current() == (
            "基础资料：米米号 123456（用户操作，群：987654321）"
        )


def test_headless_operation_context_captures_semantic_request() -> None:
    operations = HeadlessOperationTracker()
    request = SemanticRequest(
        action=ActionDefinition("seer.player.collection", "收集与排行"),
        target=SemanticTarget("712345678", "米米号 712345678"),
        source=SemanticRequestSource.MENU,
    )

    with (
        semantic_request_scope(request, user_id=123456),
        operations.track("收集查询", "米米号 712345678"),
    ):
        assert operations.format_recent_semantic() == (
            "收集与排行（seer.player.collection）：米米号 712345678"
            "（来源：menu，QQ：123456）"
        )


def test_headless_disconnect_notice_includes_recent_operation() -> None:
    async def run() -> None:
        operations = HeadlessOperationTracker()
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
            operations=operations,
            spawn=TaskOwner().create,
        )

        with operations.track(
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


def test_headless_disconnect_notice_includes_actual_request_history() -> None:
    class RequestHistory:
        def __init__(self) -> None:
            self.limits: list[int] = []

        def format_recent_request_history(self, *, limit: int = 8) -> str:
            self.limits.append(limit)
            return (
                "4481 (GET_DAILY_RANK_INFO)｜后台本地样本刷新（后台操作）"
                "｜超时 20.0秒｜0.0秒前"
            )

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
            state_notifier=notifier,
            operations=HeadlessOperationTracker(),
            spawn=TaskOwner().create,
        )
        history = RequestHistory()
        game._impl = cast("SeerEncryptConnect", history)

        await game._handle_disconnect()

        assert notices == [
            (
                False,
                (
                    "连接已断开\n"
                    "断线前实际封包：\n"
                    "4481 (GET_DAILY_RANK_INFO)｜后台本地样本刷新（后台操作）"
                    "｜超时 20.0秒｜0.0秒前"
                ),
                "无头连接",
                123456,
            )
        ]
        assert history.limits == [3, 8]

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
            operations=HeadlessOperationTracker(),
            spawn=TaskOwner().create,
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

        rank = cast(
            "RankService",
            type("FailingRank", (), {"fetch_range": fail_fetch})(),
        )
        service = rank_page_refresh.RankPageRefreshService(
            RankPageRefreshConfig(
                pages_per_run=1,
                pages_per_run_min=1,
            ),
            rank,
        )
        monkeypatch.setattr(
            rank_page_refresh.RankPageRefreshService,
            "preview",
            lambda _self, _rank_keys=None: [target],
        )
        game = cast(
            "SeerGame",
            SimpleNamespace(operations=HeadlessOperationTracker()),
        )

        result = await service.refresh(game)
        assert result.failed == 1
        assert service.backoff_remaining() > 0

        skipped = await service.refresh(game)
        assert skipped.total == 0

    asyncio.run(run())
