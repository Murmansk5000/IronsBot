from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.dependencies.utils import get_typed_signature
from nonebot.matcher import Matcher

from ironsbot.core.outbound import OutboundMessage
from ironsbot.integrations.onebot.matcher_support import bind_async
from ironsbot.integrations.onebot.replies import (
    event_sender_at_user_ids,
    run_portable_operation,
)
from ironsbot.services.portable_reply import PortableReply
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.core.message_input import MessageInputContext


@dataclass
class _Matcher:
    state: dict[object, object] = field(default_factory=dict)
    sent: list[Message] = field(default_factory=list)

    async def send(self, message: Message) -> dict[str, int]:
        self.sent.append(message)
        return {"message_id": len(self.sent)}


class _NoReceiptMatcher(_Matcher):
    async def send(self, message: Message) -> dict[str, int]:
        self.sent.append(message)
        return {}


def test_bound_portable_operation_preserves_nonebot_matcher_type() -> None:
    async def operation(
        _text: str,
        _context: MessageInputContext,
    ) -> PortableReply:
        return PortableReply(OutboundMessage.from_text("ok"))

    handler = bind_async(run_portable_operation, operation=operation)

    parameters = get_typed_signature(handler).parameters
    assert tuple(parameters) == ("matcher", "event")
    assert parameters["matcher"].annotation is Matcher


def _group_event(
    text: str = "帮助",
    *,
    user_id: int = 2,
    self_id: int = 1,
):
    return group_message_event(
        text,
        user_id=user_id,
        group_id=4,
        self_id=self_id,
    )


def _private_event(text: str = "帮助"):
    return private_message_event(
        text,
        user_id=2,
    )


def test_event_sender_at_user_ids_mentions_group_sender() -> None:
    assert event_sender_at_user_ids(_group_event()) == (2,)


def test_event_sender_at_user_ids_ignores_self_group_message() -> None:
    assert event_sender_at_user_ids(_group_event(user_id=1, self_id=1)) == ()


def test_event_sender_at_user_ids_ignores_private_sender() -> None:
    assert event_sender_at_user_ids(_private_event()) == ()


def test_event_sender_at_user_ids_ignores_missing_event() -> None:
    assert event_sender_at_user_ids(None) == ()


@pytest.mark.asyncio
async def test_portable_operation_keeps_onebot_delivery_order_and_mentions() -> None:
    matcher = _Matcher()
    delivered: list[str] = []

    async def operation(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        assert text == "开服了吗"
        assert context.message.conversation.id == "4"

        async def follow_up() -> PortableReply:
            return PortableReply(
                OutboundMessage.from_text("最终结果"),
                on_delivered=lambda: delivered.append("final"),
            )

        return PortableReply(
            OutboundMessage.from_text("正在查询"),
            on_delivered=lambda: delivered.append("initial"),
            follow_up=follow_up,
        )

    await run_portable_operation(
        cast("Matcher", matcher),
        _group_event("开服了吗"),
        operation,
    )

    assert delivered == ["initial", "final"]
    assert [str(message) for message in matcher.sent] == [
        "[CQ:at,qq=2] 正在查询",
        "[CQ:at,qq=2] 最终结果",
    ]


@pytest.mark.asyncio
async def test_portable_operation_does_not_commit_without_onebot_receipt() -> None:
    matcher = _NoReceiptMatcher()
    transitions: list[str] = []

    async def operation(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text, context
        return PortableReply(
            OutboundMessage.from_text("结果"),
            on_delivered=lambda: transitions.append("delivered"),
            on_delivery_failed=lambda: transitions.append("failed"),
        )

    await run_portable_operation(cast("Matcher", matcher), _group_event(), operation)

    assert transitions == ["failed"]
    assert len(matcher.sent) == 1
