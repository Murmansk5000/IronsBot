from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot import portable_queries
from ironsbot.plugins.onebot.seer.query.commands import player_shortcuts
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
    PortableTextInputSpec,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.plugins.onebot.seer.query.group import SeerMatcherGroup


@pytest.mark.asyncio
@pytest.mark.parametrize("interaction", ["none", "menu", "text"])
@pytest.mark.parametrize("delivered", [False, True])
async def test_initial_reply_uses_the_same_delivery_contract_with_or_without_menu(
    monkeypatch: pytest.MonkeyPatch,
    *,
    interaction: Literal["none", "menu", "text"],
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
        if interaction == "menu":
            message = sessions.offer_menu(
                context,
                PortableMenuSpec(choices=("one",), select=choose, prompt=message),
            )
        elif interaction == "text":
            message = sessions.offer_text_input(
                context,
                PortableTextInputSpec(submit=choose, prompt=message),
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
    if interaction != "none" and delivered:
        entered.assert_awaited_once()
        assert "prompt" not in entered.call_args.kwargs
    else:
        entered.assert_not_awaited()


@pytest.mark.asyncio
async def test_onebot_adapter_continues_menu_to_text_input_without_command_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = PortableQuerySessions()
    sent = AsyncMock(return_value=SendResult(delivered=True, message_id="sent-1"))
    entered = AsyncMock()
    submit = AsyncMock(return_value=OutboundMessage.from_text("saved"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", sent)
    monkeypatch.setattr(portable_queries, "enter_event_reply_conversation", entered)
    monkeypatch.setattr(
        portable_queries,
        "queued_conversation_is_cancelled",
        lambda _: False,
    )

    async def operation(text: str, context: MessageInputContext) -> OutboundMessage:
        del text

        async def choose(_value: str) -> OutboundMessage:
            return sessions.offer_text_input(
                context,
                PortableTextInputSpec(
                    submit=submit,
                    prompt=OutboundMessage.from_text("enter time"),
                ),
            )

        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("time",),
                select=choose,
                prompt=OutboundMessage.from_text("choose"),
            ),
        )

    matcher = cast("Matcher", Mock())
    handler = portable_queries.make_portable_query_handler(operation, sessions)
    await handler(matcher, {}, group_message_event("query"))
    resolve = entered.call_args.kwargs["handlers"][0]
    await resolve(matcher, group_message_event("1"), {})
    expected_prompts = ("choose", "enter time")
    assert entered.await_count == len(expected_prompts)
    assert entered.call_args.kwargs["reply_check"](group_message_event("22:30"))
    await resolve(matcher, group_message_event("22:30"), {})
    submit.assert_awaited_once_with("22:30")
    assert entered.await_count == len(expected_prompts)
    assert [call.args[2].parts for call in sent.await_args_list] == [
        OutboundMessage.from_text(text).parts for text in (*expected_prompts, "saved")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["收集", "巅峰", "群星牌", "档案"])
async def test_registered_onebot_player_shortcut_runs_shared_delivery(
    monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    async def query(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=False)
        return QueryReply(text="result", image=b"image-bytes")

    service = SimpleNamespace(shortcut=AsyncMock(side_effect=query))
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(PlayerDetailExtensionAction(
        id="sample_detail", feature="seer_player", label="档案", aliases=("档案",),
        command_help_id="sample.detail", query=service.shortcut,
        action=ActionDefinition("sample_detail", "档案"),
    ))
    matcher = Mock()
    group = SimpleNamespace(
        resources=SimpleNamespace(
            player=service, player_detail_extensions=extensions,
        ),
        features=Mock(),
        player_id_resolver=PlayerIdResolver(lambda *_: None, lambda _: 700001),
        query_sessions=PortableQuerySessions(),
        on_message=Mock(return_value=matcher),
        matcher_priority=lambda _: 5,
    )
    player_shortcuts.install(cast("SeerMatcherGroup", group))
    handler = matcher.append_handler.call_args_list[int(text == "档案")].args[0]
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="sent-1"))
    monkeypatch.setattr(portable_queries, "send_portable_event_reply", send)
    monkeypatch.setattr(
        portable_queries, "queued_conversation_is_cancelled", lambda _: False,
    )
    await handler(Mock(), {}, group_message_event(text))
    service.shortcut.assert_awaited_once()
    expected_sends = ("progress", "result")
    assert send.await_count == len(expected_sends)
    assert send.await_args is not None
    assert send.await_args.args[2] == QueryReply(
        text="result", image=b"image-bytes",
    ).to_outbound()
