# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import contextmanager
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
from ironsbot.services.messaging.subscriptions import (
    PushSubscriptionOption,
)
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinWindowBindingError,
    LuckySkinWindowLoginRequiredError,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery, MessageLimiter
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess

EXPECTED_COMMAND_ID = 45866
EXPECTED_DAILY_NOTICES = 2
EXPECTED_REQUEST_PREFIX = (668, 0, 0, 18, 203247)


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


class _Headless:
    def __init__(self, game: _Game) -> None:
        self.game = game
        self.timeouts: list[float] = []
        self.healthy_worker_count = 1
        self.login_calls = 0

    async def wait_until_available(self, *, timeout: float) -> _Game:
        self.timeouts.append(timeout)
        return self.game

    async def login(self) -> int:
        self.login_calls += 1
        self.healthy_worker_count = 1
        return 1


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


def _service(
    tmp_path: Path,
) -> tuple[
    LuckySkinWindowService,
    _Game,
    _Delivery,
    SqlitePlayerBindingStore,
    _Headless,
]:
    bindings = SqlitePlayerBindingStore(tmp_path / "qq_state.sqlite")
    bindings.bind(qq_user_id=1001, player_id=90001, player_nick="甲")
    bindings.bind(qq_user_id=1002, player_id=90002, player_nick="乙")
    game = _Game()
    headless = _Headless(game)
    service = LuckySkinWindowService(
        LuckySkinWindowConfig(
            enabled=True,
            accounts=[
                LuckySkinWindowAccountConfig(
                    user="owner",
                    player_id=90001,
                    watched_skin_ids=[101],
                ),
                LuckySkinWindowAccountConfig(
                    user="friend",
                    player_id=90002,
                    watched_skin_ids=[102],
                ),
            ],
        ),
        OneBotReferenceResolver({}, {"owner": 1001, "friend": 1002}),
        cast("FeatureService", _Features()),
        cast("HeadlessService", headless),
        cast("SeerDataAccess", _Data()),
        bindings,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
        SqliteLuckySkinWindowCache(
            tmp_path / "cache/runtime/lucky_skin_window.sqlite"
        ),
        today=lambda: date(2026, 8, 3),
    )
    return service, game, _Delivery(), bindings, headless


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
    assert all(
        body[: len(EXPECTED_REQUEST_PREFIX)] == EXPECTED_REQUEST_PREFIX
        for _command_id, body in game.calls
    )
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


def test_manual_query_requires_confirmation_before_logging_in(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, headless = _service(tmp_path)
    headless.healthy_worker_count = 0

    with pytest.raises(LuckySkinWindowLoginRequiredError):
        asyncio.run(service.check_for_user(1001))
    assert headless.login_calls == 0
    assert game.calls == []

    asyncio.run(service.login_and_check_for_user(1001))
    assert headless.login_calls == 1
    assert len(game.calls) == 1


def test_manual_query_uses_own_cached_result_without_logging_in(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, headless = _service(tmp_path)

    asyncio.run(service.check_for_user(1001))
    headless.healthy_worker_count = 0
    cached = asyncio.run(service.check_for_user(1001))

    assert cached.from_cache
    assert headless.login_calls == 0
    assert len(game.calls) == 1


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
    service, game, delivery, _bindings, headless = _service(tmp_path)
    headless.healthy_worker_count = 0

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))

    assert headless.login_calls == 1
    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES
