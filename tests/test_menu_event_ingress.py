from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves rule signatures
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, MessageSegment
from nonebot.matcher import matchers
from nonebot.message import handle_event
from nonebot.rule import Rule

from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.response_admission import ResponseAdmissionDecision
from ironsbot.core.text_matching import TextMatchRule
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.portable_queries import (
    install_portable_menu_router,
    make_portable_query_handler,
)
from ironsbot.services.portable_query_operations import build_query_operation
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
    QueryOperationSpec,
)
from ironsbot.services.seer.query_commands import AUTOCARD_QUERY
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime


@pytest.mark.asyncio
async def test_replayed_event_only_replies_once_but_new_local_message_runs(
    ingress: SimpleNamespace,
) -> None:
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress

    matchers.clear()
    messaging = _subscription_service()
    install_command_ingress(
        ingress.factory,
        _messaging_router(messaging, ingress.sessions),
        ingress.messenger,
    )
    event = group_message_event("td", user_id=101, message_id=301)
    await handle_event(ingress.bots[0], event)
    await handle_event(ingress.bots[0], event)
    assert len(ingress.sends) == 1
    await handle_event(
        ingress.bots[0], group_message_event("td", user_id=101, message_id=302)
    )
    assert len(ingress.sends) == len(("first", "second"))


def _subscription_service() -> Mock:
    from ironsbot.services.messaging.subscriptions import PushSubscriptionOption

    root = PushSubscriptionOption("bili", "赛尔号", "bili_push", submenu_key="seer")
    activity = PushSubscriptionOption("activity", "活动提醒", "seer_activity_push")
    media = PushSubscriptionOption("body", "动态正文", "bili_push")
    return Mock(
        topics=None,
        feature_policy=FeatureService({}, {}, frozenset()),
        portable_command_actions=(),
        has_enabled_mention_replies=False,
        match_action=Mock(return_value=None),
        match_mention_reply=Mock(return_value=None),
        prepared_subscription_menu=AsyncMock(
            return_value=([root, activity], "root\n1.赛尔号\n2.活动提醒\n0.【退出】")
        ),
        subscription_submenu=Mock(
            side_effect=lambda _conversation, option, **_kwargs: (
                ([media], "child\n1.动态正文\n0.【退出】") if option == root else None
            )
        ),
        toggle_subscription=Mock(return_value="已修改订阅"),
        matches_subscription_command=Mock(
            side_effect=lambda text: text.casefold() == "td"
        ),
        matches_push_time_command=Mock(return_value=False),
    )


def _messaging_router(service: Mock, sessions: PortableQuerySessions):
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService
    from ironsbot.services.messaging.command_contracts import (
        messaging_command_contracts,
    )
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_messaging_commands import (
        build_portable_messaging_operations,
    )

    operations = build_portable_messaging_operations(service, sessions)
    config = MessageConfig(commands=list(service.portable_command_actions))
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="messaging",
                commands=tuple(
                    contract
                    for contract in messaging_command_contracts(config)
                    if contract.id in operations
                ),
            ),
        ),
        known_features=("text",),
    )
    return PortableCommandRouter(
        catalog,
        operations,
        service.feature_policy,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(service.feature_policy, catalog),
        addressed_input_hints=AddressedInputHintService(),
        messaging=service,
        query_sessions=sessions,
    )


@pytest.mark.asyncio
async def test_onebot_team_confirmation_uses_real_ingress_and_owner(
    ingress: SimpleNamespace,
    tmp_path: Any,
) -> None:
    from ironsbot.config.models.seer import TeamQueryConfig, TeamResourceConfig
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.platform import ConversationRef, Platform
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress
    from ironsbot.integrations.storage.team_resources import (
        TeamResourceSubscriptionStore,
    )
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.seer.command_contracts import seer_command_contracts
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.seer.team_commands import build_team_query_operation
    from ironsbot.services.team.resource import TeamResourceService
    from ironsbot.services.team.resource_subscriptions import (
        TeamResourceSubscriptionTarget,
    )
    from tests.test_seer_team_service import FakeHeadless, TeamInfo

    conversation = ConversationRef(Platform.ONEBOT, "group", "456")
    features = FeatureService(
        {conversation: frozenset({"seer_team", "team_resource_subscription"})},
        {},
        frozenset(),
    )
    headless = FakeHeadless(TeamInfo(team_id=730001))
    service = TeamResourceService(
        TeamResourceConfig(enabled=True),
        TeamResourceSubscriptionStore(tmp_path / "team.sqlite"),
        cast("Any", headless),
        features,
        Mock(),
    )
    query = SeerTeamQueryService(
        TeamQueryConfig(),
        cast("Any", headless),
        lambda _code: None,
        service,
    )
    resolver = PlayerIdResolver(lambda *_: None, lambda _: None)
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=tuple(
                    command
                    for command in seer_command_contracts(resolver)
                    if command.id == "seer.team.query"
                ),
            ),
        ),
        known_features=("seer_team",),
    )
    router = PortableCommandRouter(
        catalog,
        {
            "seer.team.query": build_team_query_operation(
                query, resolver, features, ingress.sessions
            )
        },
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=ingress.sessions,
    )
    matchers.clear()
    install_command_ingress(ingress.factory, router, ingress.messenger)
    await handle_event(
        ingress.bots[0],
        group_message_event(
            "战队730001",
            user_id=101,
            message_id=1,
            sender={"role": "admin"},
        ),
    )
    assert len(ingress.sends) == 1
    assert "是否订阅" in str(ingress.sends[0]["message"])
    await handle_event(
        ingress.bots[0],
        group_message_event(
            "y",
            user_id=102,
            message_id=2,
            sender={"role": "admin"},
        ),
    )
    await handle_event(
        ingress.bots[1],
        group_message_event(
            "y",
            user_id=101,
            self_id=2,
            message_id=2,
            sender={"role": "admin"},
        ),
    )
    assert len(ingress.sends) == 1
    await handle_event(
        ingress.bots[0],
        group_message_event(
            "y",
            user_id=101,
            sender={"role": "admin"},
            message_id=3,
        ),
    )
    assert len(ingress.sends) == len(("suggestion", "confirmation"))
    assert "已订阅本群战队" in str(ingress.sends[-1]["message"])
    await handle_event(
        ingress.bots[0], group_message_event("y", user_id=101, message_id=4)
    )
    assert len(ingress.sends) == len(("suggestion", "confirmation"))
    assert "730001" in service.subscriptions_message(
        TeamResourceSubscriptionTarget(conversation)
    )


@pytest.mark.asyncio
async def test_onebot_public_entry_uses_shared_rank_candidates_and_final_target(
    ingress: SimpleNamespace,
) -> None:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.platform import ActorRef, ConversationRef, Platform
    from ironsbot.core.player_references import PlayerReferenceChoice
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_rank_commands import build_portable_rank_operations
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.rank_command_contracts import (
        rank_help_command_contracts,
    )
    from tests.test_portable_rank_commands import _RankQueryService

    service = _RankQueryService()
    features = FeatureService(
        {ConversationRef(Platform.ONEBOT, "group", "456"): frozenset({"seer_rank"})},
        {},
        frozenset(),
    )
    resolver = PlayerIdResolver(
        lambda value, _group: int(value) if value.isdecimal() else None,
        lambda _actor: 740001,
        reference_search=lambda *_: (
            PlayerReferenceChoice(740002, "示例甲"),
            PlayerReferenceChoice(740003, "示例乙"),
        ),
    )
    operations = build_portable_rank_operations(
        cast("Any", service), resolver, ingress.sessions, AsyncMock(), features
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="rank_help",
                commands=tuple(
                    command
                    for command in rank_help_command_contracts(resolver)
                    if command.id in operations
                ),
            ),
        ),
        known_features=("seer_rank",),
    )
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=ingress.sessions,
    )
    matchers.clear()
    install_command_ingress(ingress.factory, router, ingress.messenger)
    await handle_event(
        ingress.bots[0], group_message_event("成就榜示例", user_id=101, message_id=1)
    )
    assert len(ingress.sends) == 1
    assert service.delivered == []
    assert "示例甲" in str(ingress.sends[0]["message"])
    await handle_event(
        ingress.bots[0], group_message_event("2", user_id=101, message_id=2)
    )
    assert len(ingress.sends) == len(("candidates", "result"))
    assert service.delivered == [("成就点数", 740003)]
    assert "740003" in str(ingress.sends[-1]["message"])
    assert features.is_feature_allowed(
        ActorRef(Platform.ONEBOT, "101"),
        ConversationRef(Platform.ONEBOT, "group", "456"),
        "seer_rank",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_onebot_configured_text_real_ingress_has_only_selected_targets(
    ingress: SimpleNamespace,
    explicit: bool,  # noqa: FBT001
) -> None:
    from ironsbot.config.models.messaging import MessageCommandAction
    from ironsbot.core.platform import ActorRef, ConversationRef, Platform
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress

    service = _subscription_service()
    action = MessageCommandAction(
        id="example", commands=["示例"], messages=["示例内容"], at_user_ids=[304]
    )
    service.portable_command_actions = (action,)
    service.command_mentions = Mock(return_value=(ActorRef(Platform.ONEBOT, "304"),))
    service.feature_policy = FeatureService(
        {ConversationRef(Platform.ONEBOT, "group", "456"): frozenset({"text"})},
        {},
        frozenset(),
    )
    # The fixture's legacy menu matcher must not run alongside the production ingress.
    matchers.clear()
    install_command_ingress(
        ingress.factory, _messaging_router(service, ingress.sessions), ingress.messenger
    )
    message = Message("示例")
    if explicit:
        message += MessageSegment.at(303) + MessageSegment.at(303)
    await handle_event(
        ingress.bots[0], group_message_event(message=message, user_id=101)
    )
    assert len(ingress.sends) == 1
    sent = ingress.sends[0]["message"]
    assert [part.data["qq"] for part in sent if part.type == "at"] == [
        "303" if explicit else "304"
    ]


@pytest.mark.asyncio
async def test_onebot_registered_td_back_toggle_exit_and_reopen(
    ingress: SimpleNamespace,
) -> None:
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress

    messaging = _subscription_service()
    matchers.clear()
    install_command_ingress(
        ingress.factory,
        _messaging_router(messaging, ingress.sessions),
        ingress.messenger,
    )
    bot = ingress.bots[0]
    sequence = ("td", "1", "1", "0", "2", "0", "td")
    for message_id, value in enumerate(sequence, start=1):
        await handle_event(
            bot,
            group_message_event(
                value, user_id=101, sender={"role": "admin"}, message_id=message_id
            ),
        )
    messages = [str(sent["message"]) for sent in ingress.sends]
    assert len(messages) == len(sequence)
    assert "返回上级" in messages[1] and "返回上级" in messages[2]
    assert "root" in messages[3] and "已修改订阅" in messages[4]
    assert "已退出" in messages[5] and "root" in messages[6]
    assert [
        call.args[1].key for call in messaging.toggle_subscription.call_args_list
    ] == ["body", "activity"]


@pytest.mark.asyncio
async def test_official_parsed_td_uses_same_navigation_and_delivery() -> None:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import SendResult
    from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
    from tests.test_qq_official_mvp import _sdk_event

    sessions = PortableQuerySessions()
    messaging = _subscription_service()
    actor = qq_official_incoming_message(
        _sdk_event(content="td"), account_id="test-app"
    ).actor
    messaging.feature_policy = FeatureService({}, {}, frozenset({actor}))
    router = _messaging_router(messaging, sessions)
    messages = []
    for index, value in enumerate(("td", "1", "1", "0", "2", "0", "td")):
        event = _sdk_event(content=value)
        context = MessageInputContext(
            qq_official_incoming_message(event, account_id="test-app"),
            mentions_bot=False,
        )
        reply = await router.dispatch(context)
        assert reply is not None

        async def send(
            message: OutboundMessage,
            receipt: int = index,
        ) -> SendResult:
            result = SendResult(delivered=True, message_id=f"receipt-{receipt}")
            messages.append(str(message.parts))
            return result

        await router.delivery.deliver(context, reply, send)
    assert "返回上级" in messages[1] and "返回上级" in messages[2]
    assert "root" in messages[3] and "已修改订阅" in messages[4]
    assert "已退出" in messages[5] and "root" in messages[6]
    assert [
        call.args[1].key for call in messaging.toggle_subscription.call_args_list
    ] == ["body", "activity"]


if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.matcher_contracts import CommandCooldown


@pytest.fixture
def ingress(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    saved = dict(matchers.items())
    matchers.clear()
    sends: list[dict[str, Any]] = []

    async def api(_adapter: Adapter, bot: Bot, api: str, **data: Any) -> object:
        assert api in {"send_msg", "send_group_msg", "send_private_msg"}
        sends.append({"bot": bot.self_id, **data})
        return {"message_id": len(sends) + 100}

    monkeypatch.setattr(Adapter, "_call_api", api)
    adapter = Adapter(driver)
    sessions = PortableQuerySessions()
    cooldown = Mock()
    cooldown.admit.return_value = ResponseAdmissionDecision(allowed=True)
    factory = MatcherFactory(cast("CommandCooldown", cooldown), SimpleNamespace())
    features = FeatureService({}, {}, frozenset())
    install_portable_menu_router(factory, sessions, features)
    selected: list[tuple[str, int]] = []
    gate = asyncio.Event()
    gate.set()

    async def select(value: int, ctx: MessageInputContext) -> OutboundMessage:
        selected.append((ctx.message.actor.id, value))
        return OutboundMessage.from_text(f"result:{value}")

    async def query(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        await gate.wait()
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=tuple(range(1, 8)),
                select=select,
                prompt=OutboundMessage.from_text("menu"),
                shareable=True,
                keep_open=True,
                can_select=lambda _value, responder: (
                    responder.message.actor.id != "103"
                ),
            ),
        )

    command = factory.on_fullmatch(
        "菜单",
        policy=CommandPolicy.command("test.menu", category=RequestCategory.LOCAL),
        block=True,
    )
    command.append_handler(make_portable_query_handler(query, sessions))
    try:
        yield SimpleNamespace(
            bots=(Bot(adapter, "1"), Bot(adapter, "2")),
            sessions=sessions,
            sends=sends,
            selected=selected,
            gate=gate,
            factory=factory,
            messenger=OneBotOutboundMessenger(
                cast("Any", Mock()), build_test_runtime().outbound
            ),
        )
    finally:
        matchers.clear()
        matchers.update(saved)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "private", "admin", "policy", "expected"),
    [
        ("关于", False, False, "enabled", "about"),
        ("关于", False, False, "disabled", None),
        ("开服了吗", False, False, "enabled", "normal"),
        ("开服了吗", False, False, "disabled", None),
        ("开服了吗", False, True, "blacklist", None),
        ("/开服查询", False, False, "enabled", None),
        ("/开服查询", False, True, "enabled", "admin"),
        ("/无头状态", False, True, "enabled", None),
        ("/无头状态", True, True, "enabled", "instances"),
        ("开服查询", False, False, "enabled", "usage"),
        ("开服查询", False, False, "disabled", None),
    ],
)
async def test_status_about_real_ingress_contract(  # noqa: PLR0913 - contract matrix
    ingress: SimpleNamespace,
    text: str,
    *,
    private: bool,
    admin: bool,
    policy: str,
    expected: str | None,
) -> None:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.platform import ActorRef, ConversationRef, Platform
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.integrations.onebot.command_ingress import install_command_ingress
    from ironsbot.services.about import AboutService, about_command_contracts
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService
    from ironsbot.services.operations.server_status import ServerStatusResult
    from ironsbot.services.operations.server_status_commands import (
        server_status_command_contracts,
    )
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_operational_commands import (
        build_portable_about_operation,
        build_portable_server_status_operations,
    )
    from tests.helpers.onebot_events import private_message_event

    actor = ActorRef(Platform.ONEBOT, "101")
    group = ConversationRef(Platform.ONEBOT, "group", "456")
    allowed = frozenset({"about", "server_status_query"})
    grants = frozenset({"blacklist"}) if policy == "blacklist" else allowed
    if policy == "disabled":
        grants = frozenset()
    features = FeatureService(
        {group: grants}, {actor: grants}, frozenset({actor}) if admin else frozenset()
    )
    service = Mock(
        query_normal=AsyncMock(return_value=ServerStatusResult("normal")),
        query_admin=AsyncMock(return_value=ServerStatusResult("admin")),
        query_headless_instances=AsyncMock(
            return_value=ServerStatusResult("instances")
        ),
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="about", commands=about_command_contracts()),
            PluginContribution(
                id="server_status", commands=server_status_command_contracts()
            ),
        ),
        known_features=allowed,
    )
    router = PortableCommandRouter(
        catalog,
        {
            "about": build_portable_about_operation(AboutService("test-version")),
            **build_portable_server_status_operations(service),
        },
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=ingress.sessions,
    )
    matchers.clear()
    install_command_ingress(ingress.factory, router, ingress.messenger)
    event = (
        private_message_event(text, user_id=101)
        if private
        else group_message_event(text, user_id=101)
    )
    await handle_event(ingress.bots[0], event)
    assert len(ingress.sends) == int(expected is not None)
    for method, kind in (
        (service.query_normal, "normal"),
        (service.query_admin, "admin"),
        (service.query_headless_instances, "instances"),
    ):
        assert method.await_count == int(expected == kind)
    if expected is not None:
        rendered = str(ingress.sends[0]["message"])
        wanted = {
            "about": "test-version",
            "usage": "普通查询请发送",
        }.get(expected, expected)
        assert wanted in rendered


def _reply(text: str, *, user: int, anchor: int, shape: str = "metadata", bot: int = 1):
    message = MessageSegment.at(bot) + Message(text)
    event = group_message_event(text, user_id=user, self_id=bot, message=message)
    if shape == "metadata":
        return group_message_event(
            text,
            user_id=user,
            self_id=bot,
            message=message,
            reply_sender_user_id=bot,
            reply_message_id=anchor,
        )
    quoted = MessageSegment.reply(anchor) + message
    if shape == "message":
        event.message = quoted
    else:
        event.original_message = quoted
    return event


@pytest.mark.asyncio
async def test_onebot_query_matching_and_no_hit_cleanup_at_event_ingress(
    ingress: SimpleNamespace,
) -> None:
    sessions = ingress.sessions
    rows = {701: "星光之风", 702: "星光之影"}
    selected: list[int] = []

    async def search(argument: str) -> QueryResult[int]:
        matched = TextMatchRule(normalize_command_text).select(
            argument, rows, names=lambda id_: (rows[id_],)
        )
        return QueryResult(
            choices=tuple(
                QueryChoice(rows[id_], str(id_), id_) for id_ in matched.matches
            )
        )

    async def select(id_: int) -> QueryResult[object]:
        selected.append(id_)
        return QueryResult(reply=QueryReply(text=f"chip:{id_}"))

    def matches(event: Event) -> bool:
        return AUTOCARD_QUERY(message_input_context(event).text) is not None

    matcher = ingress.factory.on_message(
        policy=CommandPolicy.command("test.chip", category=RequestCategory.LOCAL),
        rule=Rule(matches),
        block=True,
    )
    matcher.append_handler(
        make_portable_query_handler(
            build_query_operation(
                sessions,
                QueryOperationSpec(
                    parser=AUTOCARD_QUERY.parse_argument,
                    search=search,
                    select=select,
                    prompt_title="choose",
                    keep_open=True,
                ),
            ),
            sessions,
        )
    )
    bot = ingress.bots[0]
    await handle_event(bot, group_message_event("芯片星光", user_id=101))
    assert len(ingress.sends) == 1
    await handle_event(bot, _reply("2", user=101, anchor=101))
    assert selected == [702]
    expected_messages = len(("menu", "selected"))
    assert len(ingress.sends) == expected_messages
    await handle_event(bot, group_message_event("芯片没拿好也是卒", user_id=101))
    await handle_event(bot, group_message_event("1", user_id=101))
    assert len(ingress.sends) == expected_messages
    context = message_input_context(group_message_event(user_id=101))
    assert sessions.menu_anchor(context) is None
    assert not sessions.recognizes_response("1", context)


@pytest.mark.asyncio
async def test_unknown_player_query_clears_menu_without_reply(
    ingress: SimpleNamespace,
) -> None:
    bot = ingress.bots[0]
    await handle_event(bot, group_message_event("菜单", user_id=101))
    sent = len(ingress.sends)
    await handle_event(bot, group_message_event("米米号不存在的玩家", user_id=101))
    await handle_event(bot, group_message_event("1", user_id=101))
    assert len(ingress.sends) == sent
    assert not ingress.selected
    assert not ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=101))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["metadata", "message", "original"])
async def test_real_event_cross_member_sessions_are_independent(
    ingress: SimpleNamespace, shape: str
) -> None:
    bot = ingress.bots[0]
    await handle_event(bot, group_message_event("菜单", user_id=101))
    assert len(ingress.sends) == 1
    await handle_event(bot, group_message_event("1", user_id=101))
    await handle_event(bot, _reply("2", user=102, anchor=101, shape=shape))
    await handle_event(bot, group_message_event("3", user_id=102))
    await handle_event(bot, _reply("3", user=102, anchor=101, shape=shape))
    await handle_event(bot, group_message_event("0", user_id=101))
    await handle_event(bot, group_message_event("7", user_id=102))
    assert ingress.selected == [
        ("101", 1),
        ("102", 2),
        ("102", 3),
        ("102", 3),
        ("102", 7),
    ]
    assert not ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=101))
    )
    assert ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=102))
    )
    for sent in ingress.sends[2:4]:
        assert MessageSegment.at(102) in sent["message"]


@pytest.mark.asyncio
async def test_quotes_cannot_cross_bot_or_result_and_denial_keeps_own_menu(
    ingress: SimpleNamespace,
) -> None:
    first, second = ingress.bots
    await handle_event(first, group_message_event("菜单", user_id=101))
    await handle_event(second, group_message_event("菜单", user_id=101, self_id=2))
    await handle_event(first, group_message_event("菜单", user_id=103))
    own = ingress.sessions.active_prompt(
        message_input_context(group_message_event(user_id=103))
    )
    await handle_event(first, _reply("1", user=103, anchor=101))
    assert (
        ingress.sessions.active_prompt(
            message_input_context(group_message_event(user_id=103))
        )
        == own
    )
    await handle_event(second, _reply("1", user=102, anchor=101, bot=2))
    await handle_event(first, _reply("1", user=101, anchor=999))
    await handle_event(first, group_message_event("1", user_id=101))
    await handle_event(first, _reply("2", user=101, anchor=105))
    assert ingress.selected == [("101", 1)]


@pytest.mark.asyncio
async def test_early_seven_is_queued_fifo_and_new_command_replaces_menu(
    ingress: SimpleNamespace,
) -> None:
    bot = ingress.bots[0]
    ingress.gate.clear()
    opening = asyncio.create_task(
        handle_event(bot, group_message_event("菜单", user_id=101))
    )
    for _ in range(100):
        if ingress.sessions.recognizes_response(
            "7", message_input_context(group_message_event(user_id=101))
        ):
            break
        await asyncio.sleep(0)
    selections = []
    for index in (1, 2, 3, 7):
        selections.append(
            asyncio.create_task(
                handle_event(bot, group_message_event(str(index), user_id=101))
            )
        )
        await asyncio.sleep(0)
    ingress.gate.set()
    await asyncio.gather(opening, *selections)
    assert ingress.selected == [("101", index) for index in (1, 2, 3, 7)]
    await handle_event(bot, group_message_event("菜单", user_id=101))
    await handle_event(bot, _reply("1", user=101, anchor=101))
    assert ingress.selected == [("101", index) for index in (1, 2, 3, 7)]
