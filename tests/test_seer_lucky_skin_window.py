# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from struct import pack
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

from ironsbot.config.models.seer import (
    LuckySkinWindowAccountConfig,
    LuckySkinWindowConfig,
    PlayerAccountConfig,
)
from ironsbot.config.player_accounts import build_player_account_registry
from ironsbot.core.messaging import DeliveryReceipt, MessageTarget, TargetSendSummary
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.storage.lucky_skin_watch import (
    SqliteLuckySkinWatchPreferenceStore,
)
from ironsbot.integrations.storage.lucky_skin_window import (
    SqliteLuckySkinWindowCache,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.seer import lucky_skin_window as lucky_skin_window_plugin
from ironsbot.plugins.seer import lucky_skin_window_query
from ironsbot.services.messaging.subscriptions import (
    PushSubscriptionOption,
)
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinWindowBindingError,
    LuckySkinWindowOffer,
    LuckySkinWindowResult,
    LuckySkinWindowService,
    _parse_skin_ids,
)
from ironsbot.services.seer.query_result import QueryReply, QueryResult
from ironsbot.services.seer.skin_price import SkinStorePrice
from tests.helpers.onebot_events import private_message_event
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery, MessageLimiter
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.seer.data import SeerDataAccess

EXPECTED_COMMAND_ID = 45866
EXPECTED_DAILY_NOTICES = 2
EXPECTED_SCHEDULE_SECOND = 5
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
_OWNER_USER_ID = 1001
_OWNER_PLAYER_ID = 90001
WATCH_SKIN_ID = 103


class _Features:
    def is_private_feature_allowed(self, _user_id: int, _feature: str) -> bool:
        return True


class _Data:
    pet_skin = object()
    skins: ClassVar[dict[int, SimpleNamespace]] = {
        skin_id: SimpleNamespace(
            id=skin_id,
            resource_id=1_400_000 + skin_id,
            name=f"皮肤{skin_id}",
        )
        for skin_id in (101, 102, 103, 104, 105)
    }

    @contextmanager
    def get_many(
        self,
        _getter: object,
        ids: set[int],
    ) -> Iterator[dict[int, Any]]:
        yield {skin_id: self.skins[skin_id] for skin_id in ids if skin_id in self.skins}

    @contextmanager
    def resolve(self, _getter: object, arg: str) -> Iterator[tuple[Any, ...]]:
        yield tuple(skin for skin in self.skins.values() if arg in skin.name)

    @contextmanager
    def query(self, operation: Any) -> Iterator[Any]:
        keywords = operation.keywords
        if "skin_ids" in keywords:
            yield {
                skin_id: SkinStorePrice(
                    skin_id=skin_id,
                    pool_id=1,
                    price=298,
                    original_price=398,
                    discount_rate=0,
                    selected_price=0,
                    ticket_id=1_727_935,
                    ticket_num=20,
                    start_time=0,
                    end_time=0,
                )
                for skin_id in keywords["skin_ids"]
            }
            return
        references = frozenset(keywords["references"])
        yield tuple(
            skin for skin in self.skins.values() if skin.resource_id in references
        )


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
        values = (0,) * 8 + (101, 102, 103, 104)
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
        self.batches = 0

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
    async def send_target_messages(  # noqa: PLR0913
        self,
        target_messages: Iterable[tuple[MessageTarget, Any]],
        *,
        bot: Any | None = None,
        action_name: str = "message action",
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
        receipt_handler: Any | None = None,
        verify_history: bool = False,
    ) -> TargetSendSummary:
        del bot, action_name, message_limiter, verify_history
        selected = list(target_messages)
        self.batches += 1
        self.messages.extend(
            ([target], str(message), subscription_key)
            for target, message in selected
        )
        if receipt_handler is not None:
            for target, _message in selected:
                receipt_handler(
                    DeliveryReceipt(
                        target=target,
                        bot_id=2947993138,
                        message_id=target.target_id,
                        history_status="confirmed",
                    )
                )
        return TargetSendSummary([target for target, _message in selected], [])

    def default_bot(self) -> None:
        return None

    def bot_for_target(self, _target: MessageTarget) -> None:
        return None


class _Scheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def get_jobs(self) -> list[object]:
        return []

    def remove_job(self, _job_id: str) -> None:
        return None


class _PluginService:
    def __init__(self, *, cached: object | None) -> None:
        self.cached = cached
        self.queries = 0

    def cached_for_user(self, _user_id: int) -> object | None:
        return self.cached

    def account_for_user(self, _user_id: int) -> SimpleNamespace:
        return SimpleNamespace(player_id=90001)

    def can_login_account(self, user_id: int, player_id: int) -> bool:
        return user_id == _OWNER_USER_ID and player_id == _OWNER_PLAYER_ID

    def account_for_player_id(self, player_id: int) -> SimpleNamespace | None:
        return (
            SimpleNamespace(player_id=player_id)
            if player_id in {90001, 90002}
            else None
        )

    def cached_for_account(self, _player_id: int) -> object | None:
        return self.cached

    async def check_for_user(self, _user_id: int) -> object:
        self.queries += 1
        return object()

    async def check_for_account(self, _player_id: int) -> object:
        self.queries += 1
        return object()

    def format_result(self, _result: object, *, user_id: int) -> str:
        return f"橱窗结果：{user_id}"

    async def render_result(self, _result: object, *, user_id: int) -> bytes | None:
        del user_id
        return None


class _PetQuery:
    async def select_image(self, _selection: object) -> object:
        return SimpleNamespace(message="", reply=None)


def _service(
    tmp_path: Path,
    *,
    legacy_cache_path: Path | None = None,
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
                    account="owner_account",
                    watched_skin_ids=[1_400_101],
                ),
                LuckySkinWindowAccountConfig(
                    user="friend",
                    account="friend_account",
                    watched_skin_ids=[102],
                ),
            ],
        ),
        OneBotReferenceResolver({}, {"owner": 1001, "friend": 1002}),
        build_player_account_registry(
            [
                PlayerAccountConfig(
                    player_id=90001,
                    name="owner_account",
                    password="owner-secret",
                ),
                PlayerAccountConfig(
                    player_id=90002,
                    name="friend_account",
                    password="friend-secret",
                ),
            ]
        ),
        cast("FeatureService", _Features()),
        cast("Any", sessions),
        cast("SeerDataAccess", _Data()),
        bindings,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
        SqliteLuckySkinWatchPreferenceStore(tmp_path / "qq_state.sqlite"),
        SqliteLuckySkinWindowCache(
            tmp_path / "runtime_state.sqlite",
            legacy_paths=(() if legacy_cache_path is None else (legacy_cache_path,)),
        ),
        today=lambda: date(2026, 8, 3),
    )
    return service, game, _Delivery(), bindings, sessions


def test_daily_schedule_uses_configured_second(tmp_path: Path) -> None:
    service, _game, delivery, _bindings, _sessions = _service(tmp_path)
    scheduler = _Scheduler()

    lucky_skin_window_plugin._register_schedule(
        service,
        cast("MessageDelivery", delivery),
        cast("Scheduler", scheduler),
    )

    daily_job = next(
        job for job in scheduler.jobs if job["id"] == "lucky_skin_window:daily"
    )
    assert daily_job["hour"] == 0
    assert daily_job["minute"] == 1
    assert daily_job["second"] == EXPECTED_SCHEDULE_SECOND
    assert daily_job["timezone"] == "Asia/Shanghai"


def test_query_requires_the_configured_player_binding(tmp_path: Path) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    async def check() -> None:
        result = await service.check_for_user(1001)
        assert [offer.skin_id for offer in result.offers] == [101, 102, 103, 104]
        owner_message = service.format_result(result, user_id=1001)
        friend_message = service.format_result(result, user_id=1002)
        assert "皮肤101（皮肤ID：101，资源ID：1400101） ★ 关注" in owner_message
        assert "皮肤102（皮肤ID：102，资源ID：1400102） ★ 关注" in friend_message

    asyncio.run(check())
    bindings.bind(qq_user_id=1001, player_id=90003, player_nick="其他")
    with pytest.raises(LuckySkinWindowBindingError, match="90001"):
        asyncio.run(service.check_for_user(1001))


def test_render_result_marks_the_receivers_own_watched_skin(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)
    rendered_offers: list[tuple[LuckySkinWindowOffer, ...]] = []

    async def render_result(
        result: LuckySkinWindowResult,
        offers: tuple[LuckySkinWindowOffer, ...],
    ) -> bytes:
        del result
        rendered_offers.append(offers)
        return b"lucky-window-image"

    service._renderer = render_result  # type: ignore[assignment]

    async def check() -> None:
        result = await service.check_for_user(1001)

        owner_image = await service.render_result(result, user_id=1001)
        friend_image = await service.render_result(result, user_id=1002)
        assert owner_image == b"lucky-window-image"
        assert friend_image == b"lucky-window-image"

    asyncio.run(check())

    owner_offers, friend_offers = rendered_offers
    assert [offer.watched for offer in owner_offers] == [True, False, False, False]
    assert [offer.watched for offer in friend_offers] == [False, True, False, False]


def test_daily_notifications_accept_a_rendered_message_formatter(
    tmp_path: Path,
) -> None:
    service, _game, delivery, _bindings, _headless = _service(tmp_path)

    async def format_message(
        result: LuckySkinWindowResult,
        *,
        user_id: int,
    ) -> str:
        del result
        return f"image:{user_id}"

    asyncio.run(
        service.send_daily_notifications(
            cast("MessageDelivery", delivery),
            format_message=format_message,
        )
    )

    assert {message for _targets, message, _key in delivery.messages} == {
        "image:1001",
        "image:1002",
    }


def test_lucky_skin_response_uses_the_first_of_four_offers() -> None:
    # The following uint is unrelated metadata.  Starting at index 9 would
    # omit skin 705 and incorrectly include 50 as the last offer.
    values = (0, 0, 0, 18, 0, 0, 0, 0, 705, 338, 239, 207, 50)

    assert _parse_skin_ids(pack(f"!{len(values)}I", *values)) == (
        705,
        338,
        239,
        207,
    )


def test_watch_defaults_accept_resource_ids_and_seed_only_once(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    assert [
        (item.skin_id, item.resource_id)
        for item in service.watched_skins(1001)
    ] == [(101, 1_400_101)]

    service.config.accounts[0].watched_skin_ids = [1_400_102]
    assert service.clear_watched_skins(1001)
    assert service.watched_skins(1001) == ()

    reset = service.reset_watched_skins(1001)
    assert [(item.skin_id, item.resource_id) for item in reset] == [
        (102, 1_400_102)
    ]


def test_watch_management_accepts_both_ids_and_names(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    by_id = service.resolve_watch_candidates(1001, str(WATCH_SKIN_ID))
    by_resource_id = service.resolve_watch_candidates(1001, "1400103")
    by_name = service.resolve_watch_candidates(1001, f"皮肤{WATCH_SKIN_ID}")

    assert by_id == by_resource_id == by_name
    assert by_id[0].skin_id == WATCH_SKIN_ID
    assert service.add_watched_skin(1001, by_id[0].skin_id)
    assert not service.add_watched_skin(1001, by_id[0].skin_id)
    assert service.remove_watched_skin(1001, by_id[0].skin_id)
    assert not service.remove_watched_skin(1001, by_id[0].skin_id)


def test_watch_preferences_are_isolated_by_qq_user(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    assert service.add_watched_skin(1001, 104)
    assert [item.skin_id for item in service.watched_skins(1001)] == [101, 104]
    assert [item.skin_id for item in service.watched_skins(1002)] == [102]


def test_empty_watch_preference_remains_initialized(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    store = SqliteLuckySkinWatchPreferenceStore(path)

    assert store.get(1001) is None
    store.set(1001, ())

    assert SqliteLuckySkinWatchPreferenceStore(path).get(1001) == ()


def test_watch_command_rules_distinguish_list_and_change(tmp_path: Path) -> None:
    _service_instance, _game, _delivery, _bindings, _headless = _service(tmp_path)
    features = cast("FeatureService", _Features())

    async def check() -> None:
        list_state: dict[str, object] = {}
        for commands in (
            lucky_skin_window_plugin._WATCH_LIST_COMMANDS,
            lucky_skin_window_plugin._WATCH_CLEAR_COMMANDS,
            lucky_skin_window_plugin._WATCH_RESET_COMMANDS,
        ):
            for command in commands:
                assert await lucky_skin_window_plugin._matches_watch_exact(
                    private_message_event(command, user_id=1001),
                    cast("Any", list_state),
                    commands=commands,
                    features=features,
                )

        for commands in (
            lucky_skin_window_plugin._WATCH_LIST_COMMANDS,
            lucky_skin_window_plugin._WATCH_REMOVE_COMMANDS,
        ):
            for command in commands:
                change_state: dict[str, object] = {}
                assert await lucky_skin_window_plugin._matches_watch_change(
                    private_message_event(f"{command} 1400103", user_id=1001),
                    cast("Any", change_state),
                    commands=commands,
                    features=features,
                )
                assert (
                    change_state[lucky_skin_window_plugin.BOT_COMMAND_ARG_KEY]
                    == "1400103"
                )

        assert not await lucky_skin_window_plugin._matches_watch_change(
            private_message_event("关注橱窗", user_id=1001),
            cast("Any", {}),
            commands=lucky_skin_window_plugin._WATCH_LIST_COMMANDS,
            features=features,
        )
        for legacy_command in ("关注皮肤", "订阅皮肤"):
            assert not await lucky_skin_window_plugin._matches_watch_exact(
                private_message_event(legacy_command, user_id=1001),
                cast("Any", {}),
                commands=lucky_skin_window_plugin._WATCH_LIST_COMMANDS,
                features=features,
            )

    asyncio.run(check())


def test_lucky_skin_commands_run_before_fuzzy_pet_skin_queries(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)
    runtime = build_test_runtime(state_path=tmp_path / "runtime_state.sqlite")
    registry = runtime.matcher_registry()

    lucky_skin_window_plugin._install(
        registry,
        service=service,
        pet_query=cast("Any", _PetQuery()),
        features=cast("FeatureService", _Features()),
    )

    assert registry.message_matchers
    assert all(
        matcher.priority == runtime.matcher_priorities.lucky_skin_window
        for matcher in registry.message_matchers
    )
    assert (
        runtime.matcher_priorities.lucky_skin_window
        < runtime.matcher_priorities.seer_pet
    )


def test_watch_list_matches_before_binding_and_replies_with_the_problem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)
    bindings.bind(qq_user_id=1001, player_id=90003, player_nick="其他")
    event = private_message_event("订阅橱窗", user_id=1001)
    replies: list[str] = []

    async def capture_reply(
        _matcher: object,
        _event: object,
        message: str,
    ) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_plugin, "finish_event_reply", capture_reply)

    async def check() -> None:
        assert await lucky_skin_window_plugin._matches_watch_exact(
            event,
            cast("Any", {}),
            commands=lucky_skin_window_plugin._WATCH_LIST_COMMANDS,
            features=cast("FeatureService", _Features()),
        )
        await lucky_skin_window_plugin._handle_watch_list(
            service,
            cast("Any", object()),
            event,
        )

    asyncio.run(check())

    assert replies == ["❌ 请先绑定 TOML 指定的米米号 90001 后再管理橱窗关注。"]


def test_watch_list_displays_both_skin_ids(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    message = lucky_skin_window_plugin._format_watch_list(
        service.watched_skins(1001)
    )

    assert "皮肤ID：101，资源ID：1400101" in message


def test_daily_results_are_cached_per_configured_player(tmp_path: Path) -> None:
    service, game, delivery, _bindings, _headless = _service(tmp_path)

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))

    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert {command_id for command_id, _body in game.calls} == {EXPECTED_COMMAND_ID}
    assert all(body == EXPECTED_REQUEST for _command_id, body in game.calls)
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES
    assert delivery.batches == 1
    messages = {
        targets[0].target_id: message
        for targets, message, _key in delivery.messages
    }
    assert "皮肤101（皮肤ID：101，资源ID：1400101） ★ 关注" in messages[1001]
    assert "皮肤102（皮肤ID：102，资源ID：1400102） ★ 关注" in messages[1002]
    assert all(
        key == LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY
        for _targets, _message, key in delivery.messages
    )

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))
    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES


def test_daily_notifications_log_query_and_delivery_receipts(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    service, _game, delivery, _bindings, _headless = _service(tmp_path)
    caplog.set_level(logging.INFO, logger="ironsbot.services.seer.lucky_skin_window")

    asyncio.run(service.send_daily_notifications(cast("MessageDelivery", delivery)))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "daily task started" in message and "targets=2" in message
        for message in messages
    )
    assert any(
        "daily query succeeded" in message
        and "player_id=90001" in message
        and "skin_ids=(101, 102, 103, 104)" in message
        for message in messages
    )
    assert any(
        "daily delivery receipt" in message
        and "player_id=90001" in message
        and "message_id=1001" in message
        and "history_status=confirmed" in message
        for message in messages
    )


def test_daily_delivery_history_failure_is_logged_without_a_notification(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)
    target = MessageTarget("private", 1001)
    caplog.set_level(logging.ERROR, logger="ironsbot.services.seer.lucky_skin_window")

    service._log_daily_delivery_receipt(
        DeliveryReceipt(
            target=target,
            bot_id=2947993138,
            message_id=1001,
            history_status="missing",
            history_error="get_msg returned no message",
        ),
        day="2026-08-29",
        contexts={target: (90001, (101, 102, 103, 104))},
    )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert "player_id=90001" in caplog.records[0].getMessage()
    assert "history_error=get_msg returned no message" in caplog.records[0].getMessage()


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


def test_only_the_configured_and_bound_user_can_login_an_account(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    assert service.can_login_account(1001, 90001)
    assert not service.can_login_account(1002, 90001)
    assert not service.can_login_account(1001, 90002)

    bindings.bind(qq_user_id=1001, player_id=90003, player_nick="其他")
    assert not service.can_login_account(1001, 90001)


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


def test_daily_result_survives_service_recreation(tmp_path: Path) -> None:
    first, _game, _delivery, _bindings, first_sessions = _service(tmp_path)
    asyncio.run(first.check_for_user(1001))
    assert len(first_sessions.opens) == 1

    recreated, _game, _delivery, _bindings, recreated_sessions = _service(tmp_path)
    cached = asyncio.run(recreated.check_for_user(1001))

    assert cached.from_cache
    assert recreated_sessions.opens == []


def test_legacy_cache_for_the_same_account_survives_a_storage_upgrade(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "cache/runtime/lucky_skin_window.sqlite"
    legacy_cache = SqliteLuckySkinWindowCache(legacy_path)
    legacy_cache.prepare_day(day="2026-08-03")
    legacy_cache.put_if_absent(
        player_id=90001,
        skin_ids=(101, 102, 103, 104),
    )

    service, game, _delivery, _bindings, sessions = _service(
        tmp_path,
        legacy_cache_path=legacy_path,
    )
    cached = asyncio.run(service.check_for_user(1001))

    assert cached.from_cache
    assert sessions.opens == []
    assert game.calls == []
    assert SqliteLuckySkinWindowCache(tmp_path / "runtime_state.sqlite").get(
        player_id=90001,
        day="2026-08-03",
    ) == (101, 102, 103, 104)


def test_legacy_cache_never_crosses_configured_accounts(tmp_path: Path) -> None:
    legacy_path = tmp_path / "cache/runtime/lucky_skin_window.sqlite"
    legacy_cache = SqliteLuckySkinWindowCache(legacy_path)
    legacy_cache.prepare_day(day="2026-08-03")
    legacy_cache.put_if_absent(
        player_id=90002,
        skin_ids=(101, 102, 103, 104),
    )

    service, game, _delivery, _bindings, sessions = _service(
        tmp_path,
        legacy_cache_path=legacy_path,
    )

    assert service.cached_for_user(1001) is None
    assert sessions.opens == []
    assert game.calls == []


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


def test_configured_lucky_window_account_can_be_looked_up_and_checked_by_id(
    tmp_path: Path,
) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)
    target_id = 90_002

    account = service.account_for_player_id(target_id)
    result = asyncio.run(service.check_for_account(target_id))

    assert account is not None
    assert account.player_id == target_id
    assert result.player_id == target_id
    assert len(game.calls) == 1
    assert sessions.opens[0][0] == target_id
    assert len(sessions.opens) == 1
    assert service.account_for_player_id(99999) is None


def test_manual_query_prompts_before_a_missing_daily_cache_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=None)
    prompts: list[dict[str, object]] = []

    async def enter_conversation(*_args: object, **kwargs: object) -> None:
        prompts.append(kwargs)

    monkeypatch.setattr(
        lucky_skin_window_query,
        "enter_event_reply_conversation",
        enter_conversation,
    )

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_query(
            cast("Any", service),
            cast("Any", _PetQuery()),
            None,
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
            cast("Any", {}),
            target_key=lucky_skin_window_plugin._QUERY_TARGET_KEY,
            reference_key=lucky_skin_window_plugin._QUERY_REFERENCE_KEY,
            login_namespace="test_lucky_skin_window",
            enter_result_prompt=cast(
                "Any", lucky_skin_window_plugin._enter_result_prompt
            ),
        )
    )

    assert service.queries == 0
    assert len(prompts) == 1
    prompt = str(prompts[0]["prompt"])
    assert "90001" not in prompt
    assert "米米号" not in prompt
    assert "回复“是”或“y”确认" in prompt
    reply_check = cast("Any", prompts[0]["reply_check"])
    group_reply_check = cast("Any", prompts[0]["group_reply_check"])
    assert reply_check(private_message_event("y", user_id=1001))
    assert not reply_check(private_message_event("y", user_id=1002))
    assert group_reply_check(private_message_event("y", user_id=1001))
    assert not group_reply_check(private_message_event("y", user_id=1002))


def test_manual_query_returns_today_cache_without_a_confirmation_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=object())
    prompts: list[tuple[object, object]] = []

    async def enter_result(
        _pet_query: object,
        _matcher: object,
        _event: object,
        _state: object,
        captured_service: object,
        result: object,
    ) -> None:
        prompts.append((captured_service, result))

    monkeypatch.setattr(lucky_skin_window_plugin, "_enter_result_prompt", enter_result)

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_query(
            cast("Any", service),
            cast("Any", _PetQuery()),
            None,
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
            cast("Any", {}),
            target_key=lucky_skin_window_plugin._QUERY_TARGET_KEY,
            reference_key=lucky_skin_window_plugin._QUERY_REFERENCE_KEY,
            login_namespace="test_lucky_skin_window",
            enter_result_prompt=cast("Any", enter_result),
        )
    )

    assert service.queries == 0
    assert prompts == [(service, service.cached)]


def test_lucky_window_cross_account_query_requires_a_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=object())
    replies: list[str] = []

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_query, "finish_event_reply", finish_reply)
    state: dict[str, object] = {
        lucky_skin_window_plugin._QUERY_TARGET_KEY: (
            lucky_skin_window_plugin.PlayerTargetResolution(
                90002,
                offer_binding=False,
            )
        ),
    }

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_query(
            cast("Any", service),
            cast("Any", _PetQuery()),
            cast("Any", SimpleNamespace(is_superuser=lambda _user_id: False)),
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
            cast("Any", state),
            target_key=lucky_skin_window_plugin._QUERY_TARGET_KEY,
            reference_key=lucky_skin_window_plugin._QUERY_REFERENCE_KEY,
            login_namespace="test_lucky_skin_window",
            enter_result_prompt=cast(
                "Any", lucky_skin_window_plugin._enter_result_prompt
            ),
        )
    )

    assert replies == ["❌ 只能查询你本人已配置的幸运橱窗账号。"]
    assert service.queries == 0


def test_lucky_window_superuser_reuses_the_selected_account_cache() -> None:
    service = _PluginService(cached=object())
    prompts: list[tuple[object, object]] = []

    async def enter_result(
        _pet_query: object,
        _matcher: object,
        _event: object,
        _state: object,
        captured_service: object,
        result: object,
    ) -> None:
        prompts.append((captured_service, result))

    state: dict[str, object] = {
        lucky_skin_window_plugin._QUERY_TARGET_KEY: (
            lucky_skin_window_plugin.PlayerTargetResolution(
                90002,
                offer_binding=False,
            )
        ),
    }
    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_query(
            cast("Any", service),
            cast("Any", _PetQuery()),
            cast("Any", SimpleNamespace(is_superuser=lambda _user_id: True)),
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
            cast("Any", state),
            target_key=lucky_skin_window_plugin._QUERY_TARGET_KEY,
            reference_key=lucky_skin_window_plugin._QUERY_REFERENCE_KEY,
            login_namespace="test_lucky_skin_window",
            enter_result_prompt=cast("Any", enter_result),
        )
    )

    assert prompts == [(service, service.cached)]
    assert service.queries == 0


def test_lucky_window_superuser_cannot_login_another_users_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=None)
    replies: list[str] = []
    state: dict[str, object] = {
        lucky_skin_window_plugin._QUERY_TARGET_KEY: (
            lucky_skin_window_plugin.PlayerTargetResolution(
                90002,
                offer_binding=False,
            )
        ),
    }

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_query, "finish_event_reply", finish_reply)

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_query(
            cast("Any", service),
            cast("Any", _PetQuery()),
            cast("Any", SimpleNamespace(is_superuser=lambda _user_id: True)),
            cast("Any", object()),
            cast("Any", SimpleNamespace(user_id=1001)),
            cast("Any", state),
            target_key=lucky_skin_window_plugin._QUERY_TARGET_KEY,
            reference_key=lucky_skin_window_plugin._QUERY_REFERENCE_KEY,
            login_namespace="test_lucky_skin_window",
            enter_result_prompt=cast(
                "Any", lucky_skin_window_plugin._enter_result_prompt
            ),
        )
    )

    assert replies == ["❌ 只能由该账号的绑定用户本人确认登录。"]
    assert service.queries == 0


def test_lucky_window_cards_enter_the_existing_skin_detail_selection_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, _sessions = _service(tmp_path)
    result = asyncio.run(service.check_for_user(1001))
    captured: dict[str, object] = {}

    async def enter_prompt(
        _matcher: object,
        _event: object,
        _state: object,
        prompt: object,
        resolver: object,
        *,
        prompt_message: object,
    ) -> None:
        captured.update(
            prompt=prompt,
            resolver=resolver,
            prompt_message=await cast("Any", prompt_message),
        )

    monkeypatch.setattr(lucky_skin_window_plugin, "enter_prompt", enter_prompt)

    asyncio.run(
        lucky_skin_window_plugin._enter_result_prompt(
            cast("Any", _PetQuery()),
            cast("Any", object()),
            private_message_event("橱窗", user_id=1001),
            cast("Any", {}),
            service,
            result,
        )
    )

    prompt = cast("Any", captured["prompt"])
    assert [item.value.skin_id for item in prompt.items] == [101, 102, 103, 104]
    assert "发送 1-4" in str(captured["prompt_message"])


def test_lucky_window_selection_reuses_pet_query_reply_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[QueryReply] = []

    class PetQuery:
        async def select_image(self, _selection: object) -> QueryResult[object]:
            return QueryResult(reply=QueryReply(text="皮肤详情"))

    async def send_reply(
        _matcher: object,
        _event: object,
        message: object,
    ) -> None:
        sent.append(QueryReply(text=str(message)))

    monkeypatch.setattr(lucky_skin_window_plugin, "send_event_reply", send_reply)
    event = private_message_event("1", user_id=1001)
    item = lucky_skin_window_plugin.PromptItem(
        "皮肤",
        "101",
        lucky_skin_window_plugin.PetImageSelection(1_400_101, "皮肤", 101),
    )

    asyncio.run(
        lucky_skin_window_plugin._handle_skin_selection(
            cast("Any", PetQuery()),
            item,
            cast("Any", object()),
            event,
        )
    )

    assert [reply.text for reply in sent] == ["皮肤详情"]


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
    prompts: list[object] = []

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_query, "finish_event_reply", finish_reply)

    async def enter_result(
        _pet_query: object,
        _matcher: object,
        _event: object,
        _state: object,
        _service: object,
        result: object,
    ) -> None:
        prompts.append(result)

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_confirmation(
            cast("Any", service),
            cast("Any", _PetQuery()),
            cast("Any", object()),
            cast(
                "Any",
                SimpleNamespace(user_id=1001, get_plaintext=lambda: reply),
            ),
            cast("Any", {}),
            enter_result_prompt=cast("Any", enter_result),
        )
    )

    assert service.queries == expected_queries
    if reply == "y":
        assert replies == []
        assert len(prompts) == 1
    else:
        assert replies == [expected_message]
        assert prompts == []


def test_lucky_window_login_confirmation_rejects_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PluginService(cached=None)
    replies: list[str] = []

    async def finish_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(lucky_skin_window_query, "finish_event_reply", finish_reply)

    asyncio.run(
        lucky_skin_window_query.handle_lucky_skin_window_confirmation(
            cast("Any", service),
            cast("Any", _PetQuery()),
            cast("Any", object()),
            cast(
                "Any",
                SimpleNamespace(user_id=1002, get_plaintext=lambda: "y"),
            ),
            cast("Any", {}),
            enter_result_prompt=cast(
                "Any", lucky_skin_window_plugin._enter_result_prompt
            ),
            target_player_id=90001,
            authorized_user_id=1001,
        )
    )

    assert service.queries == 0
    assert replies == []


def test_cache_deletes_previous_days_at_the_first_new_day_lookup(
    tmp_path: Path,
) -> None:
    cache = SqliteLuckySkinWindowCache(
        tmp_path / "runtime_state.sqlite"
    )
    cache.prepare_day(day="2026-08-02")
    cache.put_if_absent(
        player_id=90001,
        skin_ids=(101, 102, 103, 104),
    )

    cache.prepare_day(day="2026-08-03")

    assert cache.get(player_id=90001, day="2026-08-03") is None


def test_storage_upgrade_discards_results_from_the_old_decoder(tmp_path: Path) -> None:
    path = tmp_path / "runtime_state.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE ironsbot_schema_migrations (
                namespace TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO ironsbot_schema_migrations
            VALUES ('skin_window', 3, '2026-08-05T00:00:00Z');
            CREATE TABLE lucky_skin_window_cache (
                player_id INTEGER PRIMARY KEY,
                skin_ids_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            INSERT INTO lucky_skin_window_cache
            VALUES (90001, '[338,239,207,50]', '2026-08-05T00:00:00Z');
            """
        )

    cache = SqliteLuckySkinWindowCache(path)

    assert cache.get(player_id=90001, day="2026-08-05") is None


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
