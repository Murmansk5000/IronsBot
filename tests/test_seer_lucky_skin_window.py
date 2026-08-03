# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from struct import pack
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import (
    LuckySkinWindowAccountConfig,
    LuckySkinWindowConfig,
)
from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.storage.lucky_skin_window import (
    SqliteLuckySkinWindowCache,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.seer import lucky_skin_window as lucky_skin_window_plugin
from ironsbot.services.messaging.subscriptions import (
    PushSubscriptionOption,
)
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinWindowBindingError,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery, MessageLimiter
    from ironsbot.services.seer.data import SeerDataAccess

EXPECTED_COMMAND_ID = 45866
EXPECTED_DAILY_NOTICES = 2
EXPECTED_REQUEST = (
    0,
    0,
    18,
    203247,
    31101,
    31102,
    31103,
    31104,
    108937,
    108938,
    108939,
    108940,
    108941,
    108942,
    108943,
    401009,
    401010,
    401007,
    401008,
    351005,
    351004,
)


class _Features:
    def is_private_feature_allowed(self, _user_id: int, _feature: str) -> bool:
        return True


class _Data:
    pet_skin = object()

    @contextmanager
    def get_many(
        self,
        _getter: object,
        ids: set[int],
    ) -> Iterator[dict[int, Any]]:
        yield {
            skin_id: SimpleNamespace(name=f"皮肤{skin_id}")
            for skin_id in ids
        }


class _Game:
    def __init__(self) -> None:
        self.operations = HeadlessOperationTracker()
        self.calls: list[tuple[int, tuple[object, ...]]] = []

    async def send_and_wait(
        self,
        command_id: Any,
        *body: object,
        timeout: float | None = None,
    ) -> tuple[None, bytes]:
        del timeout
        self.calls.append((int(command_id), body))
        values = (0,) * 9 + (101, 102, 103, 104)
        return None, pack(f"!{len(values)}I", *values)


class _Sessions:
    def __init__(self, game: _Game) -> None:
        self.game = game
        self.opens: list[tuple[int, str, str]] = []
        self.open_delay = 0.0
        self.active = 0
        self.max_active = 0

    @asynccontextmanager
    async def open(
        self,
        *,
        user_id: int,
        password: str,
        label: str = "extension",
    ):
        self.opens.append((user_id, password, label))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.open_delay:
                await asyncio.sleep(self.open_delay)
            yield self.game
        finally:
            self.active -= 1


class _Delivery:
    def __init__(self) -> None:
        self.messages: list[tuple[list[MessageTarget], str, str | None]] = []

    async def send_targets(  # noqa: PLR0913 - MessageDelivery protocol signature
        self,
        targets: Iterable[MessageTarget],
        message: Any,
        *,
        bot: Any | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        del bot, action_name, interval_seconds, message_limiter
        selected = list(targets)
        self.messages.append(
            (
                selected,
                str(message),
                subscription_key,
            )
        )
        return TargetSendSummary(selected, [])

    async def broadcast(
        self,
        message: Any,
        **_kwargs: object,
    ) -> TargetSendSummary:
        del message
        return TargetSendSummary([], [])

    def default_bot(self) -> None:
        return None

    def bot_for_target(self, _target: MessageTarget) -> None:
        return None


class _PluginService:
    def __init__(self, *, cached: object | None) -> None:
        self.cached = cached
        self.queries = 0

    def cached_for_user(self, _user_id: int) -> object | None:
        return self.cached

    def account_for_user(self, _user_id: int) -> SimpleNamespace:
        return SimpleNamespace(player_id=90001)

    async def check_for_user(self, _user_id: int) -> object:
        self.queries += 1
        return object()

    def format_result(self, _result: object, *, user_id: int) -> str:
        return f"橱窗结果：{user_id}"


def _service(
    tmp_path: Path,
) -> tuple[
    LuckySkinWindowService,
    _Game,
    _Delivery,
    SqlitePlayerBindingStore,
    _Sessions,
]:
    bindings = SqlitePlayerBindingStore(tmp_path / "qq_state.sqlite")
    bindings.bind(qq_user_id=1001, player_id=90001, player_nick="甲")
    bindings.bind(qq_user_id=1002, player_id=90002, player_nick="乙")
    game = _Game()
    sessions = _Sessions(game)
    service = LuckySkinWindowService(
        LuckySkinWindowConfig(
            enabled=True,
            accounts=[
                LuckySkinWindowAccountConfig(
                    user="owner",
                    player_id=90001,
                    password="owner-secret",
                    watched_skin_ids=[101],
                ),
                LuckySkinWindowAccountConfig(
                    user="friend",
                    player_id=90002,
                    password="friend-secret",
                    watched_skin_ids=[102],
                ),
            ],
        ),
        OneBotReferenceResolver({}, {"owner": 1001, "friend": 1002}),
        cast("FeatureService", _Features()),
        cast("Any", sessions),
        cast("SeerDataAccess", _Data()),
        bindings,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
        SqliteLuckySkinWindowCache(
            tmp_path / "cache/runtime/lucky_skin_window.sqlite"
        ),
        today=lambda: date(2026, 8, 3),
    )
    return service, game, _Delivery(), bindings, sessions


def test_query_requires_the_configured_player_binding(tmp_path: Path) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    async def check() -> None:
        result = await service.check_for_user(1001)
        assert [offer.skin_id for offer in result.offers] == [101, 102, 103, 104]
        assert "皮肤101（皮肤ID：101） ★ 关注" in service.format_result(
            result,
            user_id=1001,
        )
        assert "皮肤102（皮肤ID：102） ★ 关注" in service.format_result(
            result,
            user_id=1002,
        )

    asyncio.run(check())
    bindings.bind(qq_user_id=1001, player_id=90003, player_nick="其他")
    with pytest.raises(LuckySkinWindowBindingError, match="90001"):
        asyncio.run(service.check_for_user(1001))


def test_daily_results_are_cached_per_configured_player(tmp_path: Path) -> None:
    service, game, delivery, _bindings, _headless = _service(tmp_path)

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))

    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert {command_id for command_id, _body in game.calls} == {EXPECTED_COMMAND_ID}
    assert all(body == EXPECTED_REQUEST for _command_id, body in game.calls)
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES
    messages = {
        targets[0].target_id: message
        for targets, message, _key in delivery.messages
    }
    assert "皮肤101（皮肤ID：101） ★ 关注" in messages[1001]
    assert "皮肤102（皮肤ID：102） ★ 关注" in messages[1002]
    assert all(
        key == LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY
        for _targets, _message, key in delivery.messages
    )

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))
    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES


def test_subscription_option_requires_the_matching_binding(tmp_path: Path) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    options = service.subscription_options("private", 1001)
    assert options == [
        PushSubscriptionOption(
            key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
            label="幸运橱窗提醒",
            feature="lucky_skin_window",
        )
    ]
    assert service.subscription_options("group", 1001) == []

    bindings.bind(qq_user_id=1001, player_id=90003, player_nick="其他")
    assert service.subscription_options("private", 1001) == []


def test_manual_query_uses_its_configured_isolated_account(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.check_for_user(1001))

    assert sessions.opens == [
        (90001, "owner-secret", "幸运橱窗")
    ]
    assert len(game.calls) == 1


def test_manual_query_uses_own_cached_result_without_logging_in(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.check_for_user(1001))
    cached = asyncio.run(service.check_for_user(1001))

    assert cached.from_cache
    assert len(sessions.opens) == 1
    assert len(game.calls) == 1


def test_cache_probe_never_opens_a_dedicated_session(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    assert service.cached_for_user(1001) is None
    assert sessions.opens == []
    assert game.calls == []

    asyncio.run(service.check_for_user(1001))
    cached = service.cached_for_user(1001)

    assert cached is not None
    assert cached.from_cache
    assert len(sessions.opens) == 1


def test_manual_query_prompts_before_a_missing_daily_cache_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=None)
    prompts: list[dict[str, object]] = []

    async def enter_conversation(*_args: object, **kwargs: object) -> None:
        prompts.append(kwargs)

    monkeypatch.setattr(
        lucky_skin_window_plugin,
        "enter_event_reply_conversation",
        enter_conversation,
    )

    asyncio.run(
        lucky_skin_window_plugin._handle_query(
            cast("Any", service),
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
        )
    )

    assert service.queries == 0
    assert len(prompts) == 1
    assert "米米号：90001" in str(prompts[0]["prompt"])
    assert "回复“是”或“y”确认" in str(prompts[0]["prompt"])


def test_manual_query_returns_today_cache_without_a_confirmation_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=object())
    replies: list[str] = []

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_plugin, "finish_event_reply", finish_reply)

    asyncio.run(
        lucky_skin_window_plugin._handle_query(
            cast("Any", service),
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
        )
    )

    assert service.queries == 0
    assert replies == ["橱窗结果：1001"]


@pytest.mark.parametrize(
    ("reply", "expected_queries", "expected_message"),
    [
        ("否", 0, "已取消幸运橱窗查询。"),
        ("y", 1, "橱窗结果：1001"),
    ],
)
def test_lucky_window_login_confirmation_controls_dedicated_login(
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
    expected_queries: int,
    expected_message: str,
) -> None:
    service = _PluginService(cached=None)
    replies: list[str] = []

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_plugin, "finish_event_reply", finish_reply)

    asyncio.run(
        lucky_skin_window_plugin._handle_login_confirmation(
            cast("Any", service),
            cast("Any", object()),
            cast(
                "Any",
                SimpleNamespace(user_id=1001, get_plaintext=lambda: reply),
            ),
        )
    )

    assert service.queries == expected_queries
    assert replies == [expected_message]


def test_cache_deletes_previous_days_at_the_first_new_day_lookup(
    tmp_path: Path,
) -> None:
    cache = SqliteLuckySkinWindowCache(
        tmp_path / "cache/runtime/lucky_skin_window.sqlite"
    )
    cache.prepare_day(day="2026-08-02")
    cache.put_if_absent(
        player_id=90001,
        skin_ids=(101, 102, 103, 104),
    )

    cache.prepare_day(day="2026-08-03")

    assert cache.get(player_id=90001) is None


def test_daily_notice_logs_in_automatically(tmp_path: Path) -> None:
    service, game, delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))

    assert sessions.opens == [
        (90001, "owner-secret", "幸运橱窗"),
        (90002, "friend-secret", "幸运橱窗"),
    ]
    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES


def test_different_accounts_never_open_dedicated_sessions_concurrently(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    sessions.open_delay = 0.01

    async def check_both() -> None:
        await asyncio.gather(
            service.check_for_user(1001),
            service.check_for_user(1002),
        )

    asyncio.run(check_both())

    assert sessions.max_active == 1
    assert [user_id for user_id, _password, _label in sessions.opens] == [
        90001,
        90002,
    ]
