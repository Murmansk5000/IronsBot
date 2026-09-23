from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE
from qqbot_agent_sdk.event_parser import EventParser

from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.qq_official.runtime import deliver_qq_official_reply
from ironsbot.integrations.qq_official.sdk_client import QQOfficialSendReceipt
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
        else:
            raw["message_reference"] = {"message_id": quote}
    event = EventParser.parse("GROUP_AT_MESSAGE_CREATE", raw)
    assert event is not None
    return MessageInputContext(
        qq_official_incoming_message(event, account_id="app"), mentions_bot=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["scene", "elements", "reference"])
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
    await dispatch(_event("B", "2", quote="actual-index", shape=shape))
    assert select.await_count == len(("A", "B"))
    assert select.await_args_list[1].args[1].message.actor.id == "B"
    # Source exits; the new participant continues without quoting again.
    await dispatch(_event("A", "0"))
    await dispatch(_event("B", "1"))
    assert select.await_args is not None
    assert select.await_args.args[1].message.actor.id == "B"
    assert not router.recognizes(_event("B", "2", quote="stale-result", shape=shape))
