from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.integrations.onebot import portable_queries
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.core.message_input import MessageInputContext


@pytest.mark.asyncio
@pytest.mark.parametrize("has_menu", [False, True])
@pytest.mark.parametrize("delivered", [False, True])
async def test_initial_reply_uses_the_same_delivery_contract_with_or_without_menu(
    monkeypatch: pytest.MonkeyPatch,
    *,
    has_menu: bool,
    delivered: bool,
) -> None:
    sessions = PortableQuerySessions()
    sent = AsyncMock(
        return_value=SendResult(
            delivered=delivered,
            message_id="sent-1" if delivered else None,
            error_code=None if delivered else "rejected",
        )
    )
    entered = AsyncMock()
    success, failure = Mock(), Mock()
    follow_up = AsyncMock(return_value=OutboundMessage.from_text("finished"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    monkeypatch.setattr(portable_queries, "enter_event_reply_conversation", entered)
    monkeypatch.setattr(
        portable_queries, "queued_conversation_is_cancelled", lambda _: False
    )

    async def choose(_choice: str) -> OutboundMessage:
        return OutboundMessage.from_text("selected")

    async def operation(text: str, context: MessageInputContext) -> PortableReply:
        del text
        message = OutboundMessage.from_text("choose")
        if has_menu:
            message = sessions.offer_menu(
                context,
                PortableMenuSpec(choices=("one",), select=choose, prompt=message),
            )
        return PortableReply(
            message,
            additional_messages=(OutboundMessage.from_text("extra"),),
            on_delivered=success,
            on_delivery_failed=failure,
            follow_up=follow_up,
        )

    handler = portable_queries.make_portable_query_handler(operation, sessions)
    await handler(cast("Matcher", Mock()), {}, group_message_event("query"))

    if delivered:
        success.assert_called_once_with()
        failure.assert_not_called()
        follow_up.assert_awaited_once_with()
        assert [call.args[2].parts for call in sent.await_args_list] == [
            OutboundMessage.from_text(text).parts
            for text in ("choose", "extra", "finished")
        ]
    else:
        failure.assert_called_once_with()
        success.assert_not_called()
        follow_up.assert_not_awaited()
        sent.assert_awaited_once()
    if has_menu and delivered:
        entered.assert_awaited_once()
        assert "prompt" not in entered.call_args.kwargs
    else:
        entered.assert_not_awaited()
