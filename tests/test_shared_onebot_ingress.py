from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, MessageSegment
from nonebot.matcher import matchers
from nonebot.message import handle_event

from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
)
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.command_ingress import install_command_ingress
from ironsbot.integrations.onebot.matchers import MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)

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
    transport = Mock(fails=False)

    async def api(_adapter: Adapter, _bot: Bot, _api: str, **data: Any) -> object:
        sends.append(data)
        return {} if transport.fails else {"message_id": len(sends) + 100}

    monkeypatch.setattr(Adapter, "_call_api", api)
    group = ConversationRef(Platform.ONEBOT, "group", "456")
    policies = {group: frozenset({"help"})}
    features = FeatureService(
        policies,
        {},
        frozenset(),
    )
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
    )
    factory = MatcherFactory(sessions.interactions.cooldown, SimpleNamespace())
    install_command_ingress(factory, router)
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
            group=group,
            ai=ai,
        )
    finally:
        matchers.clear()
        matchers.update(saved)


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
