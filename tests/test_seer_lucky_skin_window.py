# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import date
from struct import pack
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

from ironsbot.config.models.seer import PlayerAccountConfig
from ironsbot.config.models.seer_lucky import (
    LuckySkinWindowAccountConfig,
    LuckySkinWindowConfig,
)
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.lucky_skin_window import (
    OneBotLuckySkinWindowSubscriptionOptions,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.seer_data.skin_price_repository import (
    load_active_skin_store_prices,
)
from ironsbot.integrations.storage.lucky_skin_watch import (
    SqliteLuckySkinWatchPreferenceStore,
)
from ironsbot.integrations.storage.lucky_skin_window import (
    SqliteLuckySkinWindowCache,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.onebot import lucky_skin_window as lucky_skin_window_plugin
from ironsbot.services.identity.player_accounts import build_player_account_registry
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.portable_lucky_skin_commands import (
    build_portable_lucky_skin_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.lucky_skin_commands import (
    LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
    LUCKY_SKIN_WATCH_LIST_COMMANDS,
    LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
    LUCKY_SKIN_WATCH_RESET_COMMANDS,
)
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
    LuckySkinQuery,
    LuckySkinWindowAccessError,
    LuckySkinWindowAccount,
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
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.pet_query import PetImageSelection

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


def test_lucky_skin_schedule_preserves_configured_seconds() -> None:
    jobs: list[dict[str, object]] = []

    class Scheduler:
        def add_job(
            self,
            func: object,
            trigger: str,
            **kwargs: object,
        ) -> None:
            jobs.append({"func": func, "trigger": trigger, **kwargs})

    service = SimpleNamespace(
        enabled=True,
        config=LuckySkinWindowConfig(enabled=True, time="00:02:19"),
        clear_previous_days=lambda: None,
        send_daily_notifications=lambda: None,
    )

    lucky_skin_window_plugin._register_schedule(
        cast("Any", service),
        cast("Any", Scheduler()),
    )

    assert jobs[1]["id"] == "lucky_skin_window:daily"
    assert (jobs[1]["hour"], jobs[1]["minute"], jobs[1]["second"]) == (0, 2, 19)


WATCH_SKIN_ID = 103


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _request(user_id: int) -> LuckySkinQuery:
    return LuckySkinQuery(_actor(user_id), _actor(user_id))


class _Features:
    def is_actor_superuser(self, actor: ActorRef) -> bool:
        return actor.id == "9999"

    def actor_has_feature(self, _actor: ActorRef, _feature: str) -> bool:
        return True

    def is_feature_allowed(
        self,
        _actor: ActorRef,
        _conversation: ConversationRef,
        _feature: str,
    ) -> bool:
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
    prices: ClassVar[dict[int, SkinStorePrice]] = {
        skin_id: SkinStorePrice(
            skin_id=skin_id,
            pool_id=1,
            price=100 + skin_id,
            original_price=200 + skin_id,
            discount_rate=0,
            selected_price=0,
            ticket_id=1,
            ticket_num=2,
            start_time=0,
            end_time=0,
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
        if operation.func is load_active_skin_store_prices:
            skin_ids = operation.keywords["skin_ids"]
            yield {
                skin_id: self.prices[skin_id]
                for skin_id in skin_ids
                if skin_id in self.prices
            }
            return
        references = frozenset(operation.keywords["references"])
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


class _NotificationSender:
    def __init__(self) -> None:
        self.messages: list[tuple[ActorRef, str | LuckySkinWindowResult, str]] = []
        self._sent: set[tuple[ActorRef, str]] = set()

    async def send_daily_notice(
        self,
        actor: ActorRef,
        message: Any,
        *,
        day: str,
    ) -> bool:
        if (actor, day) in self._sent:
            return False
        self._sent.add((actor, day))
        self.messages.append((actor, message, day))
        return True


class _PluginPet:
    async def select_image(
        self,
        selection: PetImageSelection,
    ) -> QueryResult[object]:
        return QueryResult(reply=QueryReply(text=f"皮肤详情：{selection.skin_id}"))


def _service(
    tmp_path: Path,
    *,
    renderer: Callable[
        [LuckySkinWindowResult, tuple[LuckySkinWindowOffer, ...]],
        Awaitable[bytes],
    ]
    | None = None,
) -> tuple[
    LuckySkinWindowService,
    _Game,
    _NotificationSender,
    SqlitePlayerBindingStore,
    _Sessions,
]:
    bindings = SqlitePlayerBindingStore(tmp_path / "qq_state.sqlite")
    bindings.bind(actor=_actor(1001), player_id=90001, player_nick="甲")
    bindings.bind(actor=_actor(1002), player_id=90002, player_nick="乙")
    game = _Game()
    sessions = _Sessions(game)
    config = LuckySkinWindowConfig(
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
    )
    player_accounts = build_player_account_registry(
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
            PlayerAccountConfig(
                player_id=90003,
                name="unapproved_account",
                password="unapproved-secret",
            ),
        ]
    )
    notification_sender = _NotificationSender()
    service = LuckySkinWindowService(
        config,
        (
            LuckySkinWindowAccount(
                actor=_actor(1001),
                player_account=player_accounts.resolve(
                    "owner_account",
                    location="test.owner_account",
                ),
                watched_skin_ids=(1_400_101,),
            ),
            LuckySkinWindowAccount(
                actor=_actor(1002),
                player_account=player_accounts.resolve(
                    "friend_account",
                    location="test.friend_account",
                ),
                watched_skin_ids=(102,),
            ),
        ),
        cast("FeatureService", _Features()),
        cast("Any", sessions),
        cast("SeerDataAccess", _Data()),
        bindings,
        SqliteLuckySkinWatchPreferenceStore(tmp_path / "qq_state.sqlite"),
        SqliteLuckySkinWindowCache(tmp_path / "runtime_state.sqlite"),
        notification_sender,
        today=lambda: date(2026, 8, 3),
        renderer=cast("Any", renderer),
    )
    return service, game, notification_sender, bindings, sessions


def test_query_requires_the_configured_player_binding(tmp_path: Path) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    async def check() -> None:
        result = await service.query(_request(1001))
        assert [offer.skin_id for offer in result.offers] == [101, 102, 103, 104]
        owner_message = service.format_result(result, actor=_actor(1001))
        friend_message = service.format_result(result, actor=_actor(1002))
        assert "皮肤101（皮肤ID：101，资源ID：1400101） ★ 关注" in owner_message
        assert "橱窗价：201钻（原价301钻）" in owner_message
        assert "最多用2张风尚券，最低181钻" in owner_message
        assert "皮肤102（皮肤ID：102，资源ID：1400102） ★ 关注" in friend_message
        outbound = await service.result_message(result, actor=_actor(1001))
        assert isinstance(outbound.parts[0], TextPart)
        assert outbound.parts[0].text == owner_message

    asyncio.run(check())
    bindings.bind(actor=_actor(1001), player_id=90003, player_nick="其他")
    with pytest.raises(LuckySkinWindowBindingError, match="90001"):
        asyncio.run(service.query(_request(1001)))


def test_result_message_uses_the_configured_render_port(tmp_path: Path) -> None:
    rendered_inputs: list[
        tuple[LuckySkinWindowResult, tuple[LuckySkinWindowOffer, ...]]
    ] = []

    async def render(
        result: LuckySkinWindowResult,
        offers: tuple[LuckySkinWindowOffer, ...],
    ) -> bytes:
        rendered_inputs.append((result, offers))
        return b"lucky-window-card"

    service, _game, _delivery, _bindings, _sessions = _service(
        tmp_path,
        renderer=render,
    )

    async def check() -> None:
        result = await service.query(_request(1001))
        assert (await service.result_message(result, actor=_actor(1001))).parts == (
            BinaryImagePart(b"lucky-window-card", "image/png"),
        )

    asyncio.run(check())

    assert len(rendered_inputs) == 1
    _result, offers = rendered_inputs[0]
    assert offers[0].watched is True


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
        (item.skin_id, item.resource_id) for item in service.watched_skins(_actor(1001))
    ] == [(101, 1_400_101)]

    assert service.watch_clear_message(_actor(1001)) == "已清空关注皮肤。"
    assert service.watched_skins(_actor(1001)) == ()

    reset = service.watch_reset_message(_actor(1001))
    assert "已恢复 TOML 初始关注列表。" in reset
    assert [
        (item.skin_id, item.resource_id) for item in service.watched_skins(_actor(1001))
    ] == [(101, 1_400_101)]


def test_watch_management_accepts_both_ids_and_names(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    by_id = service.resolve_watch_candidates(_actor(1001), str(WATCH_SKIN_ID))
    by_resource_id = service.resolve_watch_candidates(_actor(1001), "1400103")
    by_name = service.resolve_watch_candidates(_actor(1001), f"皮肤{WATCH_SKIN_ID}")

    assert by_id == by_resource_id == by_name
    assert by_id[0].skin_id == WATCH_SKIN_ID
    assert service.watch_change_message(
        _actor(1001), by_id[0], watched=True
    ).startswith("已关注：")
    assert service.watch_change_message(
        _actor(1001), by_id[0], watched=True
    ).startswith("已经关注：")
    assert service.watch_change_message(
        _actor(1001), by_id[0], watched=False
    ).startswith("已取消关注：")
    assert service.watch_change_message(
        _actor(1001), by_id[0], watched=False
    ).startswith("尚未关注：")


def test_watch_preferences_are_isolated_by_actor(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    item = service.resolve_watch_candidates(_actor(1001), "104")[0]
    assert service.watch_change_message(_actor(1001), item, watched=True).startswith(
        "已关注："
    )
    assert [item.skin_id for item in service.watched_skins(_actor(1001))] == [101, 104]
    assert [item.skin_id for item in service.watched_skins(_actor(1002))] == [102]


def test_empty_watch_preference_remains_initialized(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    store = SqliteLuckySkinWatchPreferenceStore(path)

    assert store.get(_actor(1001)) is None
    store.set(_actor(1001), ())

    assert SqliteLuckySkinWatchPreferenceStore(path).get(_actor(1001)) == ()


def test_watch_command_rules_distinguish_list_and_change(tmp_path: Path) -> None:
    _service_instance, _game, _delivery, _bindings, _headless = _service(tmp_path)
    features = cast("FeatureService", _Features())

    async def check() -> None:
        list_state: dict[str, object] = {}
        for commands in (
            LUCKY_SKIN_WATCH_LIST_COMMANDS,
            LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
            LUCKY_SKIN_WATCH_RESET_COMMANDS,
        ):
            for command in commands:
                assert await lucky_skin_window_plugin._matches_watch_exact(
                    private_message_event(command, user_id=1001),
                    cast("Any", list_state),
                    commands=commands,
                    features=features,
                )

        for commands in (
            LUCKY_SKIN_WATCH_LIST_COMMANDS,
            LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
        ):
            for command in commands:
                change_state: dict[str, object] = {}
                assert await lucky_skin_window_plugin._matches_watch_change(
                    private_message_event(f"{command} 1400103", user_id=1001),
                    cast("Any", change_state),
                    commands=commands,
                    features=features,
                )

        assert not await lucky_skin_window_plugin._matches_watch_change(
            private_message_event("关注橱窗", user_id=1001),
            cast("Any", {}),
            commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
            features=features,
        )
        for legacy_command in ("关注皮肤", "订阅皮肤"):
            assert not await lucky_skin_window_plugin._matches_watch_exact(
                private_message_event(legacy_command, user_id=1001),
                cast("Any", {}),
                commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
                features=features,
            )

    asyncio.run(check())


def test_lucky_skin_commands_run_before_fuzzy_pet_skin_queries(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)
    runtime = build_test_runtime(state_path=tmp_path / "runtime_state.sqlite")
    registry = runtime.matcher_factory()

    lucky_skin_window_plugin._install(
        registry,
        service=service,
        pet=cast("Any", _PluginPet()),
        features=cast("FeatureService", _Features()),
        sessions=PortableQuerySessions(),
        resolver=cast("Any", object()),
        identity_principals=IdentityPrincipalService(),
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
    tmp_path: Path,
) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)
    bindings.bind(actor=_actor(1001), player_id=90003, player_nick="其他")
    event = private_message_event("订阅橱窗", user_id=1001)
    operations = build_portable_lucky_skin_operations(
        service,
        cast("Any", _PluginPet()),
        cast("FeatureService", _Features()),
        PortableQuerySessions(),
        cast("Any", object()),
        IdentityPrincipalService(),
    )

    async def check() -> None:
        assert await lucky_skin_window_plugin._matches_watch_exact(
            event,
            cast("Any", {}),
            commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
            features=cast("FeatureService", _Features()),
        )
        reply = await operations["seer.lucky_skin_window.watch.list"](
            event.get_plaintext(),
            message_input_context(event),
        )
        assert isinstance(reply, OutboundMessage)
        assert reply.parts == (
            TextPart("❌ 请先绑定 TOML 指定的米米号 90001 后再管理橱窗关注。"),
        )

    asyncio.run(check())


def test_watch_list_displays_both_skin_ids(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, _headless = _service(tmp_path)

    message = service.watch_list_message(_actor(1001))

    assert "皮肤ID：101，资源ID：1400101" in message


def test_daily_results_are_cached_per_configured_player(tmp_path: Path) -> None:
    service, game, delivery, _bindings, _headless = _service(tmp_path)

    asyncio.run(service.send_daily_notifications())

    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert {command_id for command_id, _body in game.calls} == {EXPECTED_COMMAND_ID}
    assert all(body == EXPECTED_REQUEST for _command_id, body in game.calls)
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES
    assert all(
        isinstance(message, LuckySkinWindowResult)
        for _actor, message, _day in delivery.messages
    )
    messages = {
        int(actor.id): service.format_result(
            cast("LuckySkinWindowResult", message), actor=actor
        )
        for actor, message, _day in delivery.messages
    }
    assert "皮肤101（皮肤ID：101，资源ID：1400101） ★ 关注" in messages[1001]
    assert "皮肤102（皮肤ID：102，资源ID：1400102） ★ 关注" in messages[1002]
    asyncio.run(service.send_daily_notifications())
    assert len(game.calls) == EXPECTED_DAILY_NOTICES
    assert len(delivery.messages) == EXPECTED_DAILY_NOTICES


def test_subscription_option_requires_the_matching_binding(tmp_path: Path) -> None:
    service, _game, _delivery, bindings, _headless = _service(tmp_path)

    options = OneBotLuckySkinWindowSubscriptionOptions(
        service,
        PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
    ).subscription_options(ConversationRef(Platform.ONEBOT, "private", "1001"))
    assert options == [
        PushSubscriptionOption(
            key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
            label="幸运橱窗提醒",
            feature="lucky_skin_window",
        )
    ]
    assert (
        OneBotLuckySkinWindowSubscriptionOptions(
            service,
            PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
        ).subscription_options(ConversationRef(Platform.ONEBOT, "group", "1001"))
        == []
    )

    bindings.bind(actor=_actor(1001), player_id=90003, player_nick="其他")
    assert (
        OneBotLuckySkinWindowSubscriptionOptions(
            service,
            PushUnsubscribeStore(tmp_path / "qq_state.sqlite"),
        ).subscription_options(ConversationRef(Platform.ONEBOT, "private", "1001"))
        == []
    )


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_admin_queries_configured_account_without_own_subscription(
    tmp_path: Path,
    platform: Platform,
) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    request = LuckySkinQuery(ActorRef(platform, "9999"), None, 90002)
    assert service.cached_query(request) is None
    assert sessions.opens == []
    result = asyncio.run(service.query(request))
    assert result.player_id == request.player_id
    assert len(sessions.opens) == 1
    assert "★" not in service.format_result(result, actor=None)
    assert service.cached_query(request) is not None


def test_nonadmin_cannot_log_in_to_another_configured_account(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    request = LuckySkinQuery(_actor(1001), _actor(1001), 90002)
    with pytest.raises(LuckySkinWindowAccessError, match="尚未缓存"):
        service.cached_query(request)
    with pytest.raises(LuckySkinWindowAccessError, match="尚未缓存"):
        asyncio.run(service.query(request))
    assert sessions.opens == []


def test_nonadmin_can_read_another_accounts_existing_cache(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    generated = asyncio.run(service.query(_request(1002)))
    request = LuckySkinQuery(_actor(1001), _actor(1001), 90002)

    assert service.cached_query(request) == replace(generated, from_cache=True)
    with pytest.raises(LuckySkinWindowAccessError, match="尚未缓存"):
        asyncio.run(service.query(request))
    assert len(sessions.opens) == 1


def test_unknown_admin_target_does_not_log_in(tmp_path: Path) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    request = LuckySkinQuery(_actor(9999), None, 999999)
    with pytest.raises(LuckySkinWindowAccessError, match="未配置"):
        asyncio.run(service.query(request))
    assert sessions.opens == []


def test_admin_cannot_query_account_outside_lucky_window_allowlist(
    tmp_path: Path,
) -> None:
    service, _game, _delivery, _bindings, sessions = _service(tmp_path)
    request = LuckySkinQuery(_actor(9999), None, 90003)
    with pytest.raises(LuckySkinWindowAccessError, match="未配置"):
        asyncio.run(service.query(request))
    assert sessions.opens == []


def test_manual_query_uses_its_configured_isolated_account(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.query(_request(1001)))

    assert sessions.opens == [(90001, "owner-secret", "幸运橱窗")]
    assert len(game.calls) == 1


def test_manual_query_uses_own_cached_result_without_logging_in(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.query(_request(1001)))
    cached = asyncio.run(service.query(_request(1001)))

    assert cached.from_cache
    assert len(sessions.opens) == 1
    assert len(game.calls) == 1


def test_daily_result_survives_service_recreation(tmp_path: Path) -> None:
    first, _game, _delivery, _bindings, first_sessions = _service(tmp_path)
    asyncio.run(first.query(_request(1001)))
    assert len(first_sessions.opens) == 1

    recreated, _game, _delivery, _bindings, recreated_sessions = _service(tmp_path)
    cached = asyncio.run(recreated.query(_request(1001)))

    assert cached.from_cache
    assert recreated_sessions.opens == []


def test_cache_probe_never_opens_a_dedicated_session(tmp_path: Path) -> None:
    service, game, _delivery, _bindings, sessions = _service(tmp_path)

    assert service.cached_query(_request(1001)) is None
    assert sessions.opens == []
    assert game.calls == []

    asyncio.run(service.query(_request(1001)))
    cached = service.cached_query(_request(1001))

    assert cached is not None
    assert cached.from_cache
    assert len(sessions.opens) == 1


def test_cache_deletes_previous_days_at_the_first_new_day_lookup(
    tmp_path: Path,
) -> None:
    cache = SqliteLuckySkinWindowCache(tmp_path / "runtime_state.sqlite")
    cache.prepare_day(day="2026-08-02")
    cache.put_if_absent(
        player_id=90001,
        skin_ids=(101, 102, 103, 104),
    )

    cache.prepare_day(day="2026-08-03")

    assert cache.get(player_id=90001) is None


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

    assert cache.get(player_id=90001) is None


def test_daily_notice_logs_in_automatically(tmp_path: Path) -> None:
    service, game, delivery, _bindings, sessions = _service(tmp_path)

    asyncio.run(service.send_daily_notifications())

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
            service.query(_request(1001)),
            service.query(_request(1002)),
        )

    asyncio.run(check_both())

    assert sessions.max_active == 1
    assert [user_id for user_id, _password, _label in sessions.opens] == [
        90001,
        90002,
    ]
