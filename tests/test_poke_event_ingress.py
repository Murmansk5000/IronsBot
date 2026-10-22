from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, PokeNotifyEvent
from nonebot.matcher import Matcher

from ironsbot.config.models.features import HelpConfig
from ironsbot.config.models.transport import OneBotNoticePriorityConfig
from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.outbound import (
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.services.messaging.poke_reply import PokeReplyService

if TYPE_CHECKING:
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


def _context(platform: Platform, *, private: bool = False) -> CommandContext:
    return CommandContext(
        ActorRef(platform, "101"),
        ConversationRef(
            platform, "private" if private else "group", "101" if private else "456"
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("private", [False, True])
async def test_poke_service_owns_presentation_and_lazy_role_lookup(
    platform: Platform, *, private: bool
) -> None:
    context = _context(platform, private=private)
    candidate = Mock(poke_text=Mock(return_value="candidate"))
    candidates = Mock(return_value=[candidate])
    role = AsyncMock(return_value="admin")
    result = SendResult(delivered=True, message_id="1")
    send = AsyncMock(return_value=result)
    service = PokeReplyService(HelpConfig(), candidates=candidates)

    assert await service.handle(context, send, group_role=role) is result
    observed_context = candidates.call_args.args[0]
    assert observed_context.group_role == (None if private else "admin")
    message = send.call_args.args[0]
    assert message.parts == (
        *((MentionPart(context.actor), TextPart(" ")) if not private else ()),
        TextPart("candidate\n发送“帮助”可查看全部指令。"),
    )
    assert role.await_count == (0 if private else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_poke_service_limited_group_has_no_lookup_or_send(
    *, private: bool
) -> None:
    context = _context(Platform.ONEBOT, private=private)
    role = AsyncMock(return_value=None)
    send = AsyncMock(
        return_value=SendResult(
            delivered=False,
            error_code="unknown",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )
    )
    service = PokeReplyService(HelpConfig(hint_max_per_window=1))
    first = await service.handle(context, send, group_role=role)
    second = await service.handle(context, send, group_role=role)

    assert first is send.return_value
    assert second is (send.return_value if private else None)
    assert send.await_count == (2 if private else 1)
    assert role.await_count == (0 if private else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("role_failure", [False, True])
async def test_actual_poke_entry_uses_shared_transport_not_matcher_send(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    private: bool,
    role_failure: bool,
) -> None:
    monkeypatch.setattr(Bot, "_calling_api_hook", set())
    monkeypatch.setattr(Bot, "_called_api_hook", set())
    legacy_send = AsyncMock(side_effect=AssertionError("matcher send used"))
    monkeypatch.setattr(Matcher, "send", legacy_send)
    calls: list[tuple[str, dict[str, Any]]] = []

    async def api(_adapter: Adapter, _bot: Bot, name: str, **data: Any) -> object:
        assert _bot.self_id == "1"
        calls.append((name, data))
        if name == "get_group_member_info":
            if role_failure:
                raise OneBotActionError(retcode=1200)
            return {"role": "admin"}
        assert name == ("send_private_msg" if private else "send_group_msg")
        return {"message_id": -42}

    monkeypatch.setattr(Adapter, "_call_api", api)
    service = PokeReplyService(HelpConfig(hint_max_per_window=1))
    event = PokeNotifyEvent(
        time=0,
        self_id=1,
        post_type="notice",
        notice_type="notify",
        sub_type="poke",
        group_id=None if private else 456,
        user_id=101,
        target_id=1,
    )

    async def deliver(current: PokeNotifyEvent) -> None:
        await ingress.handle(runtime.bot, current.model_dump())

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        OneBotNoticePriorityConfig(),
        poke=service,
        spawn=asyncio.create_task,
    )
    await deliver(event)

    expected = [{"type": "text", "data": {"text": DIRECT_COMMAND_HELP_HINT_TEXT}}]
    if not private:
        expected = [
            {"type": "at", "data": {"qq": "101"}},
            {"type": "text", "data": {"text": " "}},
            *expected,
        ]
    assert calls[-1][1]["message"] == expected
    assert calls[-1][1]["user_id" if private else "group_id"] == (
        101 if private else 456
    )
    assert len(calls) == (1 if private else 2)
    initial_count = len(calls)
    legacy_send.assert_not_awaited()
    runtime.messenger._router.for_conversation.assert_not_called()

    # A poke for another target cannot consume the remaining private/group hint.
    await deliver(event.model_copy(update={"target_id": 2}))
    assert len(calls) == (1 if private else 2)
    await deliver(event)
    assert len(calls) == initial_count + int(private)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_notice_sender_rejects_wrong_account_and_identity_shape(
    runtime: SimpleNamespace, *, private: bool
) -> None:
    context = _context(Platform.ONEBOT, private=private)
    wrong = CommandContext(
        ActorRef(Platform.ONEBOT, context.actor.id, account_id="2"),
        ConversationRef(
            Platform.ONEBOT,
            context.conversation.kind,
            context.conversation.id,
            account_id="2",
        ),
    )
    result = await runtime.messenger.send_from(
        runtime.bot, wrong, OutboundMessage.from_text("notice")
    )
    assert not result.attempted
    assert result.error_code == "account_mismatch"
    if private:
        wrong = CommandContext(
            context.actor, ConversationRef(Platform.ONEBOT, "private", "other")
        )
        result = await runtime.messenger.send_from(
            runtime.bot, wrong, OutboundMessage.from_text("notice")
        )
        assert not result.attempted
    assert runtime.sends == []
