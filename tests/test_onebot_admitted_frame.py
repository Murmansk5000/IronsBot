from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from nonebot.adapters import Event  # noqa: TC002 - preprocessor injection
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.message import event_preprocessor, handle_event
from nonebot.typing import T_State  # noqa: TC002 - preprocessor injection

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot import event_ingress
from ironsbot.integrations.onebot.event_ingress import (
    ADMITTED_MESSAGE_KEY,
    AdmittedOneBotMessage,
    OneBotEventIngress,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.services.command_ingress import CommandIngress
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import (
    group_message_event,
    private_message_event,
    self_command_event,
)

if TYPE_CHECKING:
    from types import SimpleNamespace

    from ironsbot.core.message_input import MessageInputContext

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("mode", ["direct", "mention", "reply", "menu"])
async def test_admitted_context_is_decoded_once_and_shared_through_delivery(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    private: bool,
) -> None:
    decoded: list[MessageInputContext] = []
    received: list[MessageInputContext] = []
    sent: list[MessageInputContext] = []
    original_decode = event_ingress.message_input_context
    original_handle = CommandIngress.handle
    original_reply = OneBotOutboundMessenger.reply_from

    def decode(event: Event) -> MessageInputContext:
        context = original_decode(event)
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

    monkeypatch.setattr(event_ingress, "message_input_context", decode)
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
    await handle_event(runtime.bot, event)
    assert len(decoded) == 1
    assert received == decoded
    assert received[0] is decoded[0]
    assert sent and all(context is decoded[0] for context in sent)
    assert len(runtime.sends) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "wrong_type",
        "other_event",
        "wrong_account",
        "wrong_message",
        "wrong_actor",
        "wrong_conversation",
        "wrong_platform",
        "wrong_execution_platform",
    ],
)
async def test_missing_or_mismatched_frame_never_decodes_or_runs_business(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr("nonebot.message._event_preprocessors", set())

    def forbidden_decode(_event: Event) -> MessageInputContext:
        pytest.fail("command matcher must not decode unadmitted events")

    monkeypatch.setattr(event_ingress, "message_input_context", forbidden_decode)

    @event_preprocessor
    async def corrupt(event: Event, state: T_State) -> None:
        assert isinstance(event, MessageEvent)
        if mode in {"missing", "wrong_type"}:
            state.update(
                {ADMITTED_MESSAGE_KEY: object()} if mode == "wrong_type" else {}
            )
            return
        context = message_input_context(event)
        if mode == "wrong_account":
            context = replace(
                context, execution_identity=ExecutionIdentity(Platform.ONEBOT, "2")
            )
        elif mode == "wrong_message":
            context = replace(
                context, message=replace(context.message, message_id="different")
            )
        elif mode == "wrong_actor":
            context = replace(
                context,
                message=replace(
                    context.message, actor=ActorRef(Platform.ONEBOT, "999")
                ),
            )
        elif mode == "wrong_conversation":
            context = replace(
                context,
                message=replace(
                    context.message,
                    conversation=replace(context.message.conversation, id="999"),
                ),
            )
        elif mode == "wrong_platform":
            context = replace(
                context,
                message=replace(
                    context.message,
                    platform=Platform.QQ_OFFICIAL,
                ),
            )
        elif mode == "wrong_execution_platform":
            context = replace(
                context, execution_identity=ExecutionIdentity(Platform.QQ_OFFICIAL, "1")
            )
        source = event.model_copy() if mode == "other_event" else event
        state[ADMITTED_MESSAGE_KEY] = AdmittedOneBotMessage(source, context)

    await handle_event(runtime.bot, group_message_event("执行", user_id=101))
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_own_command_normalizes_public_context_without_decoding_again(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nonebot.message._event_preprocessors", set())
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=runtime.limits.features,
            self_commands=gate,
        )
    ).install()
    contexts: list[MessageInputContext] = []
    original_decode = event_ingress.message_input_context

    def decode(event: Event) -> MessageInputContext:
        context = original_decode(event)
        contexts.append(context)
        return context

    monkeypatch.setattr(event_ingress, "message_input_context", decode)
    event = self_command_event("demo 执行")
    await handle_event(runtime.bot, event)
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
    await handle_event(runtime.bot, event)
    runtime.execute.assert_not_awaited()
    assert runtime.sends == []
