from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, MessageSegment

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from tests.helpers.onebot_events import group_message_event
from tests.test_onebot_outbound_messenger import _messenger

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.message_segments import OneBotMessage
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger


@pytest.mark.parametrize("message_id", [-42, 0, 42])
def test_wire_segments_match_native_encoding_exactly(message_id: int) -> None:
    text = "<&> [CQ:at,qq=456]\n字面文本"
    message = OutboundMessage(
        (
            TextPart(text),
            BinaryImagePart(b"png", "image/png"),
            RemoteImagePart("https://example.invalid/picture.png"),
            MentionPart(ActorRef(Platform.ONEBOT, "123")),
        )
    )
    wire = render_onebot_outbound_message(
        message,
        conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
        reply_to_id=str(message_id),
    )
    expected = [
        asdict(part)
        for part in (
            MessageSegment.reply(message_id),
            MessageSegment.text(text),
            MessageSegment.image("base64://cG5n"),
            MessageSegment.image("https://example.invalid/picture.png"),
            MessageSegment.at(123),
        )
    ]
    assert wire == expected
    assert json.loads(json.dumps(wire, ensure_ascii=False, allow_nan=False)) == wire


@pytest.mark.asyncio
async def test_native_bot_sends_the_same_wire_array_without_a_message_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot(Mock(spec=Adapter), "1")
    call_api = AsyncMock(return_value={"message_id": 31})
    monkeypatch.setattr(Bot, "call_api", call_api)
    messenger: OneBotOutboundMessenger = _messenger()
    context = message_input_context(group_message_event("执行", self_id=1))
    message = OutboundMessage.from_text("结果")
    result = await messenger.reply_from(bot, context, message)
    assert result.delivered
    assert result.message_id == "31"
    call_api.assert_awaited_once()
    assert call_api.call_args.args == ("send_group_msg",)
    wire: OneBotMessage = call_api.call_args.kwargs["message"]
    assert isinstance(wire, list)
    assert all(isinstance(part, dict) for part in wire)
    assert wire[0] == {"type": "reply", "data": {"id": str(context.message.message_id)}}
    assert wire[-1] == {"type": "text", "data": {"text": "结果"}}


def test_actual_outbound_delivery_and_echo_work_without_nonebot() -> None:
    script = """
import asyncio
import importlib.abc
import sys

class RejectNoneBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'nonebot' or fullname.startswith('nonebot.'):
            raise AssertionError('unexpected framework dependency: ' + fullname)
sys.meta_path.insert(0, RejectNoneBot())

from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.config.models.transport import OneBotRoutingConfig, SelfCommandsConfig
from ironsbot.config.qq_references import QQReferenceResolver
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity, OutboundMessage
from ironsbot.core.platform import (
    ActorRef, ConversationRef, IncomingMessageRef, Platform,
)
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.message_segments import onebot_own_account_input
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.services.messaging.outbound_limits import GroupOutboundRateLimitService
from ironsbot.services.onebot_routing import OneBotRoutingPolicy
from ironsbot.services.own_commands import OwnAccountCommandPolicy

async def run():
    class Sender:
        self_id = '111'
        async def call_api(self, api, **data):
            assert api == 'send_group_msg'
            assert data['group_id'] == 456
            message = data['message']
            assert message == [
                {'type': 'reply', 'data': {'id': '-12'}},
                {'type': 'text', 'data': {'text': 'demo help'}},
            ], message
            return {'message_id': -31}

    connections = OneBotConnections()
    sender = Sender()
    connections.connect(sender)
    router = BotRouter(
        OneBotRoutingPolicy(OneBotRoutingConfig(), QQReferenceResolver({}, {})),
        connections,
    )
    limits = GroupOutboundRateLimitService(
        OutboundRateLimitConfig(enabled=False), FeatureService({}, {}, frozenset()),
        asyncio.create_task,
    )
    own = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=['demo ']))
    messenger = OneBotOutboundMessenger(router, limits, self_commands=own)
    conversation = ConversationRef(Platform.ONEBOT, 'group', '456')
    context = MessageInputContext(
        IncomingMessageRef(Platform.ONEBOT, ActorRef(Platform.ONEBOT, '111'),
            conversation, '-12', 'input'),
        mentions_bot=False,
        execution_identity=ExecutionIdentity(Platform.ONEBOT, '111'),
    )
    result = await messenger.reply_from(
        sender, context, OutboundMessage.from_text('demo help')
    )
    assert result.delivered and result.message_id == '-31'
    echo = onebot_own_account_input(
        '111', conversation, [{'type': 'text', 'data': {'text': 'demo help'}}],
        is_own_message=True,
    )
    assert own.accept(echo) is None
    assert not any(
        name == 'nonebot' or name.startswith('nonebot.') for name in sys.modules
    )

asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
