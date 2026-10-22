from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, MessageSegment
from nonebot.matcher import matchers
from nonebot.message import handle_event

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.command_ingress import install_command_ingress
from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.command_errors import COMMAND_FAILED_MESSAGE
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.messaging.outbound_limits import GroupOutboundRateLimitService
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    saved = dict(matchers.items())
    matchers.clear()
    sends: list[dict[str, Any]] = []
    transport = Mock(fails=False, error=None, response=None)
    notices = Mock(send=AsyncMock())

    async def api(_adapter: Adapter, _bot: Bot, _api: str, **data: Any) -> object:
        sends.append({"bot": _bot.self_id, **data})
        if transport.error is not None:
            raise transport.error
        if transport.response is not None:
            return transport.response
        return {} if transport.fails else {"message_id": len(sends) + 100}

    monkeypatch.setattr(Adapter, "_call_api", api)
    group = ConversationRef(Platform.ONEBOT, "group", "456")
    policies = {group: frozenset({"help"})}
    user_policies = {}
    features = FeatureService(
        policies,
        user_policies,
        frozenset(),
    )
    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    OneBotEventIngress(
        OneBotAdmissionService(messages_enabled=True, features=features)
    ).install()
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=tuple(
                    CommandContract(
                        id=id_,
                        plugin_id="test",
                        section="test",
                        examples=(text,),
                        description=text,
                        features_all=("help",),
                        category=RequestCategory.LOCAL,
                    )
                    for id_, text in (("test.query", "执行"), ("test.menu", "菜单"))
                ),
            ),
            PluginContribution(
                id="ai_chat", commands=ai_chat_command_contracts(enabled=True)
            ),
        ),
        known_features=("help", "ai_chat"),
    )
    sessions = PortableQuerySessions()
    config = CommandCooldownConfig(
        enabled=True,
        windows=[CommandCooldownWindowConfig(window_seconds=60, max_requests=1)],
    )
    sessions.interactions.request_service = InFlightRequestService(features, config)
    sessions.interactions.cooldown = CommandCooldownService(config, features)
    execute = AsyncMock(return_value=OutboundMessage.from_text("result"))
    select = AsyncMock(return_value=OutboundMessage.from_text("selected"))
    ai = Mock(chat_reply=AsyncMock(return_value="ai-result"))

    async def menu(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=(1,),
                select=select,
                prompt=OutboundMessage.from_text("choose"),
                keep_open=True,
            ),
        )

    router = PortableCommandRouter(
        catalog,
        {"test.query": execute, "test.menu": menu},
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
        admin_notices=notices,
    )
    factory = MatcherFactory(sessions.interactions.cooldown, SimpleNamespace())
    limits = GroupOutboundRateLimitService(
        OutboundRateLimitConfig(), features, TaskOwner().create
    )
    messenger = OneBotOutboundMessenger(Mock(), limits)
    install_command_ingress(factory, router, messenger)
    try:
        yield SimpleNamespace(
            bot=Bot(Adapter(driver), "1"),
            sends=sends,
            execute=execute,
            select=select,
            sessions=sessions,
            transport=transport,
            factory=factory,
            policies=policies,
            user_policies=user_policies,
            group=group,
            ai=ai,
            notices=notices,
            errors=router.delivery.errors,
            messenger=messenger,
            limits=limits,
        )
    finally:
        limits.reset()
        matchers.clear()
        matchers.update(saved)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_production_entry_does_not_call_matcher_send(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, private: bool
) -> None:
    from nonebot.matcher import Matcher

    from ironsbot.core.platform import ActorRef
    from tests.helpers.onebot_events import group_message_event, private_message_event

    if private:
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = frozenset({"help"})
    send = AsyncMock(side_effect=AssertionError("legacy matcher send invoked"))
    monkeypatch.setattr(Matcher, "send", send)
    event = (
        private_message_event("执行", user_id=101, message_id=1)
        if private
        else group_message_event("执行", user_id=101, message_id=1)
    )
    await handle_event(runtime.bot, event)
    send.assert_not_awaited()
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    assert runtime.sends[0]["bot"] == "1"
    assert runtime.sends[0]["message"][0] == {"type": "reply", "data": {"id": "1"}}
    assert (
        {"type": "at", "data": {"qq": "101"}} in runtime.sends[0]["message"]
    ) is not private
    if not private:
        assert runtime.sends[0]["message"][2] == {
            "type": "text",
            "data": {"text": "\n"},
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private,source", [(False, "user"), (True, "user"), (False, "group")]
)
async def test_blacklist_precedes_all_native_matcher_priorities(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    private: bool,
    source: str,
) -> None:
    import nonebot.message as message_runtime

    from ironsbot.core.platform import ActorRef
    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from tests.helpers.onebot_events import group_message_event, private_message_event

    monkeypatch.setattr(message_runtime, "_event_preprocessors", set())
    blocked = frozenset({"blacklist"})
    if source == "user":
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = blocked
    else:
        runtime.policies[runtime.group] = blocked
    OneBotEventIngress(
        OneBotAdmissionService(messages_enabled=True, features=runtime.limits.features)
    ).install()
    called = AsyncMock()
    earlier = runtime.factory.on_message(
        policy=CommandPolicy.exempt("test native propagation"),
        priority=-2000,
        block=False,
    )

    async def handle() -> None:
        await called()

    earlier.append_handler(handle)
    event = private_message_event if private else group_message_event
    await handle_event(runtime.bot, event("执行", user_id=101))
    called.assert_not_awaited()
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_actual_command_sends_enforce_windows_without_global_quota_hooks(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, private: bool
) -> None:
    from ironsbot.core.platform import ActorRef
    from tests.helpers.onebot_events import group_message_event, private_message_event

    monkeypatch.setattr(Bot, "_calling_api_hook", set())
    monkeypatch.setattr(Bot, "_called_api_hook", set())
    runtime.limits.config = OutboundRateLimitConfig(
        enabled=True,
        windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
        cooldown_message="outbound limit",
    )
    if private:
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = frozenset({"help"})
    event = private_message_event if private else group_message_event
    await handle_event(runtime.bot, event("执行", user_id=101, message_id=100))
    assert len(runtime.sends) == 1
    assert str(runtime.sends[0]["message"]).count("outbound limit") == int(not private)
    await handle_event(runtime.bot, event("菜单", user_id=101, message_id=101))
    assert len(runtime.sends) == (len(("result", "menu")) if private else 1)
    runtime.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_account_mismatch_is_rejected_before_business(
    runtime: SimpleNamespace,
) -> None:
    from tests.helpers.onebot_events import group_message_event

    other = Bot(runtime.bot.adapter, "2")
    await handle_event(other, group_message_event("执行", self_id=1, user_id=101))
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []
    await handle_event(
        other, group_message_event("执行", self_id=2, user_id=101, message_id=2)
    )
    runtime.execute.assert_awaited_once()
    assert runtime.sends[0]["bot"] == "2"
    runtime.messenger._router.for_conversation.assert_not_called()


@pytest.mark.asyncio
async def test_command_reply_preserves_superuser_priority_through_explicit_port(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from ironsbot.core.platform import ActorRef
    from tests.helpers.onebot_events import group_message_event

    runtime.limits.config = OutboundRateLimitConfig(
        enabled=True,
        windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
    )
    runtime.limits.features = FeatureService(
        runtime.policies, {}, frozenset({ActorRef(Platform.ONEBOT, "101")})
    )
    reserved = runtime.limits.acquire_reply(456)
    queued = asyncio.Event()
    original = runtime.limits.acquire_superuser_reply

    async def wait_for_capacity(group_id: int | None):
        queued.set()
        return await original(group_id)

    monkeypatch.setattr(runtime.limits, "acquire_superuser_reply", wait_for_capacity)
    task = asyncio.create_task(
        handle_event(runtime.bot, group_message_event("执行", user_id=101))
    )
    try:
        await asyncio.wait_for(queued.wait(), timeout=2)
        assert not task.done()
        assert runtime.sends == []
        runtime.limits.rollback(reserved.permit)
        await asyncio.wait_for(task, timeout=2)
        assert len(runtime.sends) == 1
        runtime.execute.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_wrong_connection_cannot_feed_identity_observer(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nonebot.message as message_runtime

    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from tests.helpers.onebot_events import group_message_event

    monkeypatch.setattr(message_runtime, "_event_preprocessors", set())
    observer = Mock(observe_onebot=AsyncMock())
    OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=runtime.limits.features,
            identity_observer=observer,
            errors=runtime.errors,
        )
    ).install()
    await handle_event(runtime.bot, group_message_event("执行", self_id=2, user_id=101))
    observer.observe_onebot.assert_not_awaited()
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_actual_onebot_transport_exception_uses_shared_error_boundary(
    runtime: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.helpers.onebot_events import group_message_event

    runtime.transport.error = RuntimeError("private-native-send-detail")
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=1)
    )
    runtime.notices.send.assert_awaited_once()
    assert len(runtime.sends) == 1
    assert "private-native-send-detail" not in caplog.text
    runtime.transport.error = None
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=2)
    )
    assert runtime.execute.await_count == len(("failed", "recovered"))
    assert "result" in str(runtime.sends[-1]["message"])


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, [], {}, 1.5, "abc"])
async def test_malformed_receipt_releases_request_without_retrying_original_delivery(
    runtime: SimpleNamespace, value: object
) -> None:
    from tests.helpers.onebot_events import group_message_event

    runtime.transport.response = {"message_id": value}
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=1)
    )
    assert runtime.execute.await_count == 1
    assert len(runtime.sends) == 1
    runtime.transport.response = None
    runtime.execute.reset_mock()
    runtime.sends.clear()
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=2)
    )
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_actual_preprocessor_fault_is_admin_only_and_stops_all_business(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    enabled: bool,
) -> None:
    import nonebot.message as message_runtime

    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from tests.helpers.onebot_events import group_message_event

    monkeypatch.setattr(message_runtime, "_event_preprocessors", set())
    observer = Mock(
        observe_onebot=AsyncMock(side_effect=RuntimeError("private-mirror-detail"))
    )
    ingress = OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=enabled,
            features=runtime.limits.features,
            identity_observer=observer,
            errors=runtime.errors,
        )
    )
    ingress.install()
    await handle_event(runtime.bot, group_message_event("执行", user_id=101))
    observer.observe_onebot.assert_awaited_once()
    runtime.notices.send.assert_awaited_once()
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []
    assert "private-mirror-detail" not in caplog.text


@pytest.mark.asyncio
async def test_own_account_menu_uses_public_replay_and_navigation(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ironsbot.config.models.transport import SelfCommandsConfig
    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from ironsbot.services.own_commands import OwnAccountCommandPolicy
    from tests.helpers.onebot_events import self_command_event

    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    admission = OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=runtime.limits.features,
            self_commands=OwnAccountCommandPolicy(
                SelfCommandsConfig(enabled=True, prefixes=["demo "])
            ),
        )
    )
    admission.install()

    async def deliver(text: str, message_id: int) -> None:
        event = self_command_event(text, message_id)
        await handle_event(runtime.bot, event)

    await deliver("demo 菜单", -10)
    await deliver("demo 1", -12)
    count = len(runtime.sends)
    await deliver("demo 1", -12)
    assert len(runtime.sends) == count
    runtime.select.assert_awaited_once()
    await deliver("demo 0", -14)
    assert "已退出" in str(runtime.sends[-1]["message"])
    assert all(
        not any(part["type"] == "at" for part in sent["message"])
        for sent in runtime.sends
    )


@pytest.mark.asyncio
async def test_own_account_failed_delivery_replay_is_silent_and_fresh_retry_runs(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ironsbot.config.models.transport import SelfCommandsConfig
    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from ironsbot.services.own_commands import OwnAccountCommandPolicy
    from tests.helpers.onebot_events import self_command_event

    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    admission = OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=runtime.limits.features,
            self_commands=OwnAccountCommandPolicy(
                SelfCommandsConfig(enabled=True, prefixes=["demo "])
            ),
        )
    )
    admission.install()
    runtime.transport.fails = True
    for message_id in (1, 1):
        event = self_command_event("demo 执行", message_id)
        await handle_event(runtime.bot, event)
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    runtime.transport.fails = False
    fresh = self_command_event("demo 执行", 2)
    await handle_event(runtime.bot, fresh)
    assert runtime.execute.await_count == len(("failed", "fresh"))
    assert "result" in str(runtime.sends[-1]["message"])


@pytest.mark.asyncio
@pytest.mark.parametrize("features", [frozenset(), frozenset({"blacklist"})])
async def test_own_account_transport_admission_does_not_bypass_business_policy(
    runtime: SimpleNamespace, features: frozenset[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ironsbot.config.models.transport import SelfCommandsConfig
    from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from ironsbot.services.own_commands import OwnAccountCommandPolicy
    from tests.helpers.onebot_events import self_command_event

    runtime.policies[runtime.group] = features
    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    admission = OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=runtime.limits.features,
            self_commands=OwnAccountCommandPolicy(
                SelfCommandsConfig(enabled=True, prefixes=["demo "])
            ),
        )
    )
    event = self_command_event("demo 执行")
    if "blacklist" in features:
        from nonebot.exception import IgnoredException

        with pytest.raises(IgnoredException, match="conversation_blacklisted"):
            await admission.process(event)
        assert event.get_plaintext() == "demo 执行"
    else:
        admission.install()
        await handle_event(runtime.bot, event)
        assert event.get_plaintext() == "demo 执行"
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["执行", "unclaimed"])
async def test_actual_onebot_only_blocks_input_claimed_by_public_runtime(
    runtime: SimpleNamespace, text: str
) -> None:
    from tests.helpers.onebot_events import group_message_event

    calls = Mock()
    probe = nonebot.on_message(priority=-30, block=False)

    async def record() -> None:
        calls()

    probe.append_handler(record)
    await handle_event(runtime.bot, group_message_event(text, user_id=101))
    assert calls.call_count == int(text == "unclaimed")


@pytest.mark.asyncio
@pytest.mark.parametrize("mention", [False, True])
async def test_actual_onebot_entry_uses_public_route_and_cooldown(
    runtime: SimpleNamespace, *, mention: bool
) -> None:
    from tests.helpers.onebot_events import group_message_event

    for message_id in (1, 2):
        message = Message("执行")
        if mention:
            message = MessageSegment.at(1) + message
        await handle_event(
            runtime.bot,
            group_message_event(
                "执行",
                message=message,
                user_id=101,
                message_id=message_id,
            ),
        )
    runtime.execute.assert_awaited_once()
    assert "result" in str(runtime.sends[0]["message"])
    assert "操作过于频繁" in str(runtime.sends[1]["message"])
    assert len(runtime.factory.message_matchers) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["执行", " 执行", "执行 ", "/执行"])
async def test_actual_onebot_entry_does_not_broaden_literal_commands(
    runtime: SimpleNamespace, text: str
) -> None:
    from tests.helpers.onebot_events import group_message_event

    await handle_event(runtime.bot, group_message_event(text, user_id=101))
    claimed = text == "执行"
    assert runtime.execute.await_count == int(claimed)
    assert len(runtime.sends) == int(claimed)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["business", "transport", "unclaimed"])
async def test_failed_onebot_reply_does_not_consume_shared_cooldown(
    runtime: SimpleNamespace, failure: str
) -> None:
    from tests.helpers.onebot_events import group_message_event

    runtime.transport.fails = failure == "transport"
    runtime.execute.return_value = (
        None
        if failure == "unclaimed"
        else OutboundMessage.from_text(
            "failed", request_succeeded=failure != "business"
        )
    )
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=1)
    )
    runtime.transport.fails = False
    runtime.execute.return_value = OutboundMessage.from_text("recovered")
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=2)
    )
    assert runtime.execute.await_count == len(("failed", "recovered"))
    assert "recovered" in str(runtime.sends[-1]["message"])


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["dispatch", "follow_up", "menu"])
async def test_actual_onebot_exception_is_safe_and_releases_admission(
    runtime: SimpleNamespace, stage: str
) -> None:
    from tests.helpers.onebot_events import group_message_event

    error = RuntimeError("sensitive-query-detail")
    if stage == "menu":
        await handle_event(
            runtime.bot, group_message_event("菜单", user_id=101, message_id=1)
        )
        runtime.select.side_effect = error
    elif stage == "follow_up":
        runtime.execute.return_value = PortableReply(
            OutboundMessage.from_text("initial"),
            follow_up=AsyncMock(side_effect=error),
        )
    else:
        runtime.execute.side_effect = error
    await handle_event(
        runtime.bot,
        group_message_event(
            "1" if stage == "menu" else "执行", user_id=101, message_id=2
        ),
    )
    assert COMMAND_FAILED_MESSAGE in str(runtime.sends[-1]["message"])
    assert "sensitive-query-detail" not in str(runtime.sends)
    runtime.execute.side_effect = None
    runtime.execute.return_value = OutboundMessage.from_text("recovered")
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=3)
    )
    assert "recovered" in str(runtime.sends[-1]["message"])


@pytest.mark.asyncio
async def test_menu_and_new_command_share_one_actual_onebot_entry(
    runtime: SimpleNamespace,
) -> None:
    from tests.helpers.onebot_events import group_message_event

    await handle_event(
        runtime.bot, group_message_event("菜单", user_id=101, message_id=1)
    )
    await handle_event(runtime.bot, group_message_event("1", user_id=101, message_id=2))
    runtime.select.assert_awaited_once()
    await handle_event(
        runtime.bot, group_message_event("执行", user_id=101, message_id=3)
    )
    runtime.execute.assert_awaited_once()
    context = message_input_context(group_message_event(user_id=101))
    assert not runtime.sessions.has_active_session(context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mention", "ai_allowed", "expected"),
    [
        ("执行", False, True, "result"),
        ("执行", True, True, "result"),
        ("聊聊", True, True, "ai-result"),
        ("聊聊", True, False, "请在 @ 后输入指令"),
        ("聊聊", False, True, None),
    ],
)
async def test_actual_onebot_entry_preserves_command_before_ai(
    runtime: SimpleNamespace,
    text: str,
    *,
    mention: bool,
    ai_allowed: bool,
    expected: str | None,
) -> None:
    from tests.helpers.onebot_events import group_message_event

    runtime.policies[runtime.group] = frozenset(
        {"help", "ai_chat"} if ai_allowed else {"help"}
    )
    message = Message(text)
    if mention:
        message = MessageSegment.at(1) + message
    await handle_event(
        runtime.bot, group_message_event(text, message=message, user_id=101)
    )
    if expected is None:
        assert not runtime.sends
    else:
        assert expected in str(runtime.sends[0]["message"])
    assert runtime.execute.await_count == int(text == "执行")
    assert runtime.ai.chat_reply.await_count == int(expected == "ai-result")
