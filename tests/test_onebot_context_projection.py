from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot import ingress_facts
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.services.command_ingress import CommandIngress
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import (
    group_message_event,
    private_message_event,
    self_command_event,
)

if TYPE_CHECKING:
    from types import SimpleNamespace

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("mode", ["direct", "mention", "reply", "menu"])
async def test_input_context_is_projected_once_and_shared_through_delivery(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    private: bool,
) -> None:
    decoded: list[MessageInputContext] = []
    received: list[MessageInputContext] = []
    sent: list[MessageInputContext] = []
    original_decode = ingress_facts.decode_onebot_message
    original_handle = CommandIngress.handle
    original_reply = OneBotOutboundMessenger.reply_from

    def decode(facts: OneBotMessageFacts) -> MessageInputContext:
        context = original_decode(facts)
        decoded.append(context)
        return context

    async def handle(
        self: CommandIngress, context: MessageInputContext, *args: Any, **kwargs: Any
    ) -> bool:
        received.append(context)
        return await original_handle(self, context, *args, **kwargs)

    async def reply(
        self: OneBotOutboundMessenger,
        bot: Any,
        context: MessageInputContext,
        message: Any,
    ) -> Any:
        sent.append(context)
        return await original_reply(self, bot, context, message)

    monkeypatch.setattr(ingress_facts, "decode_onebot_message", decode)
    monkeypatch.setattr(CommandIngress, "handle", handle)
    monkeypatch.setattr(OneBotOutboundMessenger, "reply_from", reply)
    if private:
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = frozenset({"help"})
    text = "菜单" if mode == "menu" else "执行"
    event = (
        private_message_event(text, user_id=101)
        if private
        else group_message_event(text, user_id=101)
    )
    if mode in {"mention", "reply"}:
        segment = (
            MessageSegment.at(1) if mode == "mention" else MessageSegment.reply(-12)
        )
        event.message = segment + Message(text)
        event.original_message = event.message.copy()
        event.raw_message = str(event.message)
    await runtime.receive(runtime.bot, event)
    assert len(decoded) == 1
    assert received == decoded
    assert received[0] is decoded[0]
    assert sent and all(context is decoded[0] for context in sent)
    assert len(runtime.sends) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["context", "execution_identity", "_ironsbot_admitted_message"]
)
async def test_provider_extensions_cannot_override_projected_command_identity(
    runtime: SimpleNamespace,
    field: str,
) -> None:
    payload = group_message_event("执行", user_id=101).model_dump()
    payload[field] = {
        "platform": "qq_official",
        "actor": "999",
        "account_id": "2",
        "message_id": "forged",
        "conversation": "other",
    }
    await runtime.received.handle(runtime.bot, payload)
    runtime.execute.assert_awaited_once()
    context = runtime.execute.call_args.args[1]
    assert context.message.actor.id == "101"
    assert context.message.conversation.id == "456"
    assert context.message.message_id == "3"
    assert context.request_bot_id == "1"
    assert context.execution_identity.platform is Platform.ONEBOT
    assert len(runtime.sends) == 1


@pytest.mark.asyncio
async def test_own_command_normalizes_public_context_without_decoding_again(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    runtime.received = replace(
        runtime.received, admission=replace(runtime.admission, self_commands=gate)
    )
    contexts: list[MessageInputContext] = []
    original_decode = ingress_facts.decode_onebot_message

    def decode(facts: OneBotMessageFacts) -> MessageInputContext:
        context = original_decode(facts)
        contexts.append(context)
        return context

    monkeypatch.setattr(ingress_facts, "decode_onebot_message", decode)
    event = self_command_event("demo 执行")
    await runtime.receive(runtime.bot, event)
    assert [context.text for context in contexts] == ["demo 执行"]
    runtime.execute.assert_awaited_once()
    normalized = runtime.execute.call_args.args[1]
    assert normalized.text == "执行"
    assert normalized is not contexts[0]
    assert normalized.message.actor == contexts[0].message.actor
    assert normalized.message.conversation == contexts[0].message.conversation
    assert normalized.message.message_id == contexts[0].message.message_id
    assert event.get_plaintext() == "demo 执行"
    assert len(runtime.sends) == 1


@pytest.mark.asyncio
async def test_incoming_self_message_cannot_impersonate_admitted_sent_command(
    runtime: SimpleNamespace,
) -> None:
    event = group_message_event("执行", user_id=int(runtime.bot.self_id))
    await runtime.receive(runtime.bot, event)
    runtime.execute.assert_not_awaited()
    assert runtime.sends == []
