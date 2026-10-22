from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.integrations.onebot.message_segments import (
    decode_onebot_segments,
    encode_onebot_message,
)
from ironsbot.integrations.onebot.red_packet import (
    is_red_packet_message,
    is_red_packet_payload,
    red_packet_group_name,
    summarize_red_packet_message,
)

if TYPE_CHECKING:
    from pytest import LogCaptureFixture

    from ironsbot.integrations.onebot.message_segments import OneBotMessage


@pytest.mark.parametrize(
    "source,detected",
    [
        ([{"type": name, "data": {"title": " title "}}], True)
        for name in (
            "redbag",
            "redpacket",
            "red_packet",
            "hongbao",
            "lucky_money",
            "REDBAG",
        )
    ]
    + [
        ([{"type": "json", "data": {key: {"items": [{"busiId": "81"}]}}}], True)
        for key in ("content", "nested")
    ]
    + [
        ([{"type": "text", "data": {"text": text}}], detected)
        for text, detected in (
            ("[QQ红包]恭喜发财", True),
            ("谁发个红包", False),
            ("hello", False),
        )
    ]
    + [
        ([{"type": "json", "data": {"info": "[redpacket:x]"}}], True),
        ([{"type": "json", "data": {"business_id": 81}}], True),
        ([{"type": "json", "data": {"business_id": 82}}], False),
    ],
)
def test_wire_detection_and_summary_match_native_display(
    source: OneBotMessage, *, detected: bool
) -> None:
    parts = decode_onebot_segments(source)
    native = Message(MessageSegment(part["type"], part["data"]) for part in parts)
    assert is_red_packet_message(parts) is detected
    assert encode_onebot_message(parts) == str(native)
    expected = (
        "title"
        if "title" in parts[0]["data"]
        else (native.extract_plain_text().strip() or str(native).strip())[:80]
    )
    assert summarize_red_packet_message(parts) == expected


@pytest.mark.parametrize("key", ["busi_id", "busiId", "business_id", "businessId"])
@pytest.mark.parametrize("value,expected", [("81", True), (81, True), ("82", False)])
def test_nested_gray_tip_notice_preserves_business_id_detection(
    key: str, value: str | int, *, expected: bool
) -> None:
    assert (
        is_red_packet_payload({"sub_type": "gray_tip", "nested": [{key: value}]})
        is expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response", [None, [], "private-marker", {}, {"group_name": None}]
)
async def test_group_metadata_absence_does_not_prevent_notice(response: object) -> None:
    connection = Mock(self_id="1", call_api=AsyncMock(return_value=response))
    assert await red_packet_group_name(connection, 456) == ""
    connection.call_api.assert_awaited_once_with(
        "get_group_info", group_id=456, no_cache=True
    )


@pytest.mark.asyncio
async def test_group_metadata_error_is_sanitized_and_cancellation_propagates(
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="ironsbot.integrations.onebot.red_packet")
    connection = Mock(
        self_id="1", call_api=AsyncMock(side_effect=RuntimeError("private-marker"))
    )
    assert await red_packet_group_name(connection, 456) == ""
    assert "error_type=RuntimeError" in caplog.text
    assert "private-marker" not in caplog.text
    connection.call_api.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await red_packet_group_name(connection, 456)


def test_protocol_and_admin_delivery_run_without_nonebot() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
from functools import partial
from ironsbot.config.models.messaging import RedPacketNoticeConfig
from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.message_segments import decode_onebot_segments
from ironsbot.integrations.onebot.red_packet import (
    is_red_packet_message, is_red_packet_payload,
    summarize_red_packet_message, red_packet_group_name,
)
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeService, AdminNoticeSendSummary,
)
from ironsbot.services.messaging.red_packet import RedPacketNoticeService
async def run():
    class Connection:
        self_id = '1'
        calls = 0
        async def call_api(self, api, **params):
            assert api == 'get_group_info'
            assert params == {'group_id':456, 'no_cache':True}
            self.calls += 1
            return {'group_name':'example'}
    class Delivery:
        calls = 0
        async def send_admin_notice(self, message, **params):
            assert params['private_actors'] == (admin,)
            assert params['group_conversations'] == (admin_group,)
            assert params['subscription_key'] == 'red_packet_notice'
            assert 'example' in message.parts[0].text
            self.calls += 1
            return AdminNoticeSendSummary((admin, admin_group), ())
    admin = ActorRef(Platform.ONEBOT, '303')
    admin_group = ConversationRef(Platform.ONEBOT, 'group', '204')
    source = ConversationRef(Platform.ONEBOT, 'group', '456')
    features = FeatureService({admin_group:frozenset({'admin_notice'})},
        {admin:frozenset({'admin_notice'})}, frozenset())
    sender, connection = Delivery(), Connection()
    service = RedPacketNoticeService(
        RedPacketNoticeConfig(), AdminNoticeService(features, sender),
    )
    parts = decode_onebot_segments('[CQ:redbag,title=packet]')
    assert is_red_packet_message(parts)
    assert is_red_packet_payload({'sub_type':'gray_tip', 'busi_id':'81'})
    context = CommandContext(ActorRef(Platform.ONEBOT, '101'), source)
    name = partial(red_packet_group_name, connection, 456)
    first = await service.handle(context,
        summary=summarize_red_packet_message(parts), conversation_name=name)
    assert first is not None
    second = await service.handle(context, summary='notice', conversation_name=name)
    assert second is None
    assert sender.calls == connection.calls == 1
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
