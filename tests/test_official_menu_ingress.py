from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE
from qqbot_agent_sdk.event_parser import EventParser

from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.qq_official.runtime import deliver_qq_official_reply
from ironsbot.integrations.qq_official.sdk_client import QQOfficialSendReceipt
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)


def _event(
    user: str, text: str, *, quote: str | None = None, shape: str = "scene"
) -> MessageInputContext:
    raw: dict[str, Any] = {
        "id": f"{user}-{text}",
        "timestamp": "2099-01-01T00:00:00+08:00",
        "group_openid": "group",
        "author": {"member_openid": user},
        "content": text,
    }
    if quote:
        raw["message_type"] = MSG_TYPE_QUOTE
        if shape == "scene":
            raw["message_scene"] = {"ext": [f"ref_msg_idx={quote}"]}
        elif shape == "elements":
            raw["msg_elements"] = [{"msg_idx": quote}]
        elif shape == "mixed":
            raw["message_scene"] = {"ext": ["ref_msg_idx=local-index"]}
            raw["message_reference"] = {"message_id": quote}
        else:
            raw["message_reference"] = {"message_id": quote}
    event = EventParser.parse("GROUP_AT_MESSAGE_CREATE", raw)
    assert event is not None
    return MessageInputContext(
        qq_official_incoming_message(event, account_id="app"), mentions_bot=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["scene", "elements", "reference", "mixed"])
async def test_parsed_official_quote_uses_actual_receipt_and_independent_sessions(
    shape: str,
) -> None:
    sessions = PortableQuerySessions()
    context = _event("A", "菜单")
    features = FeatureService(
        {context.message.conversation: frozenset({"help"})}, {}, frozenset()
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=(
                    CommandContract(
                        id="test.menu",
                        plugin_id="test",
                        section="test",
                        examples=("菜单",),
                        description="menu",
                        features_all=("help",),
                    ),
                ),
            ),
        ),
        known_features=("help",),
    )
    select = AsyncMock(return_value=OutboundMessage.from_text("result"))

    async def opening(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=(1, 2),
                select=select,
                prompt=OutboundMessage.from_text("1. one\n2. two\n0. 退出"),
                shareable=True,
                keep_open=True,
            ),
        )

    router = PortableCommandRouter(
        catalog,
        {"test.menu": opening},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    bot = AsyncMock()
    bot.send_to_group.return_value = QQOfficialSendReceipt(
        "actual-message", ("actual-index",)
    )
    messenger = QQOfficialOutboundMessenger({"app": True}, lambda _app: bot)

    async def dispatch(context: MessageInputContext) -> None:
        reply = await router.dispatch(context)
        assert reply is not None
        await deliver_qq_official_reply(
            messenger,
            context.message,
            reply,
            on_menu_sent=lambda message, result: router.record_menu_delivery(
                context, message, result
            ),
        )

    await dispatch(context)
    await dispatch(_event("A", "1"))
    anchor = "actual-message" if shape == "mixed" else "actual-index"
    assert not router.recognizes(
        _event("B", "@环源 2", quote="unrelated-message", shape=shape)
    )
    await dispatch(_event("B", "@环源 2", quote=anchor, shape=shape))
    assert select.await_count == len(("A", "B"))
    assert select.await_args_list[1].args[1].message.actor.id == "B"
    # Source exits; the new participant continues without quoting again.
    await dispatch(_event("A", "0"))
    await dispatch(_event("B", "1"))
    assert select.await_args is not None
    assert select.await_args.args[1].message.actor.id == "B"
    assert not router.recognizes(_event("B", "2", quote="stale-result", shape=shape))


@pytest.mark.asyncio
async def test_bare_shortcut_does_not_select_previous_players_menu() -> None:
    sessions = PortableQuerySessions()
    context = _event("A", "菜单")
    features = FeatureService(
        {context.message.conversation: frozenset({"help"})}, {}, frozenset()
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=(
                    CommandContract(
                        id="test.menu",
                        plugin_id="test",
                        section="test",
                        examples=("菜单",),
                        description="menu",
                        features_all=("help",),
                    ),
                    CommandContract(
                        id="test.shortcut",
                        plugin_id="test",
                        section="test",
                        examples=("收集",),
                        description="shortcut",
                        features_all=("help",),
                    ),
                ),
            ),
        ),
        known_features=("help",),
    )
    selected = AsyncMock(return_value=OutboundMessage.from_text("old player"))

    async def opening(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("collection",),
                text_inputs=(frozenset({"收集"}),),
                select=selected,
                prompt=OutboundMessage.from_text("1. 收集\n0. 退出"),
                keep_open=True,
            ),
        )

    async def shortcut(text: str, context: MessageInputContext) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text("own binding")

    router = PortableCommandRouter(
        catalog,
        {"test.menu": opening, "test.shortcut": shortcut},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    opened = await router.dispatch(context)
    assert opened is not None
    sessions.record_delivery(
        context,
        opened.message,
        SendResult(delivered=True, message_id="menu"),
    )
    bare = await router.dispatch(_event("A", "收集"))
    assert bare is not None
    assert isinstance(bare.message.parts[0], TextPart)
    assert bare.message.parts[0].text == "own binding"
    selected.assert_not_awaited()
    assert not router.recognizes(_event("A", "1", quote="menu"))


@pytest.mark.asyncio
async def test_official_direct_pet_aliases_warn_once_while_rendering() -> None:
    sessions = PortableQuerySessions()
    context = _event("A", "精灵测试精灵")
    features = FeatureService(
        {context.message.conversation: frozenset({"help"})}, {}, frozenset()
    )
    sessions.interactions.request_service = InFlightRequestService(
        features,
        CommandCooldownConfig(
            duplicate_window_seconds=60.0,
            duplicate_message="该指令重复发送；后续重复不再提醒。",
        ),
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=(
                    CommandContract(
                        id="seer.pet.query",
                        plugin_id="test",
                        section="test",
                        examples=("精灵测试精灵",),
                        description="pet",
                        features_all=("help",),
                        routing_matcher=lambda text, _ctx: text.startswith(
                            ("精灵", "魂印", "技能")
                        ),
                    ),
                ),
            ),
        ),
        known_features=("help",),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    render = Mock()

    async def operation(text: str, context: MessageInputContext) -> OutboundMessage:
        del context
        render(text)
        started.set()
        await release.wait()
        return OutboundMessage.from_text("资料图")

    router = PortableCommandRouter(
        catalog,
        {"seer.pet.query": operation},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    first_task = asyncio.create_task(router.dispatch(context))
    await started.wait()
    duplicate = await router.dispatch(_event("A", "魂印测试精灵"))
    assert duplicate is not None
    assert isinstance(duplicate.message.parts[0], TextPart)
    assert "重复" in duplicate.message.parts[0].text
    assert await router.dispatch(_event("A", "技能测试精灵")) is None
    other_task = asyncio.create_task(router.dispatch(_event("B", "精灵测试精灵")))
    await asyncio.sleep(0)
    assert [call.args[0] for call in render.call_args_list] == [
        "精灵测试精灵",
        "精灵测试精灵",
    ]
    release.set()
    first, other = await asyncio.gather(first_task, other_task)
    assert first is not None and other is not None
    assert first.on_finished is not None and other.on_finished is not None
    first.on_finished()
    other.delivery_failed()
    other.on_finished()
    assert await router.dispatch(_event("A", "魂印测试精灵")) is None
    retry = await router.dispatch(_event("B", "魂印测试精灵"))
    assert retry is not None
    assert isinstance(retry.message.parts[0], TextPart)
    assert retry.message.parts[0].text == "资料图"
    retry.delivery_failed()
    assert retry.on_finished is not None
    retry.on_finished()
