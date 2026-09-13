from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.operations.server_status import ServerStatusResult
from ironsbot.services.portable_operational_commands import (
    build_portable_meeting_operations,
    build_portable_server_status_operations,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.server_status import ServerStatusService


@dataclass
class _FakeServerStatus:
    calls: list[str]

    async def query_normal(self) -> ServerStatusResult:
        self.calls.append("normal")
        return ServerStatusResult("normal status")

    async def query_admin(self) -> ServerStatusResult:
        self.calls.append("admin")
        return ServerStatusResult("admin status")

    async def query_headless_instances(self) -> ServerStatusResult:
        self.calls.append("instances")
        return ServerStatusResult("instance status")


def _context() -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, "user", account_id="bot")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "user",
        account_id="bot",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id="message",
            text="",
        ),
        mentions_bot=False,
    )


def _text(message: object) -> str:
    assert isinstance(message, OutboundMessage)
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_portable_operational_queries_use_shared_services() -> None:
    service = _FakeServerStatus([])
    operations = {
        **build_portable_server_status_operations(
            cast("ServerStatusService", service)
        ),
        **build_portable_meeting_operations(
            "6638682008",
            "会议号：{meeting_number}\n{meeting_url}",
        ),
    }
    context = _context()

    normal = await operations["server_status.query"]("开服了吗", context)
    admin = await operations["server_status.admin_query"]("开服查询", context)
    instances = await operations["server_status.headless_instances"](
        "无头实例", context
    )
    meeting = await operations["meeting"]("会议", context)

    assert service.calls == ["normal", "admin", "instances"]
    assert _text(normal) == "normal status"
    assert _text(admin) == "admin status"
    assert _text(instances) == "instance status"
    assert _text(meeting) == (
        "会议号：663-868-2008\nhttps://meeting.tencent.com/p/6638682008"
    )


@pytest.mark.asyncio
async def test_portable_meeting_reports_missing_configuration() -> None:
    operations = build_portable_meeting_operations("", "{meeting_number}")

    result = await operations["meeting"]("会议", _context())

    assert "messaging.meeting.number" in _text(result)
