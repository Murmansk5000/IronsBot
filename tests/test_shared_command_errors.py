from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
)
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.command_errors import COMMAND_FAILED_MESSAGE
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _runtime(platform: Platform, stage: str, error: BaseException) -> SimpleNamespace:
    actor = ActorRef(platform, "caller")
    admin = ActorRef(platform, "admin")
    ordinary_group = ConversationRef(platform, "group", "ordinary-group")
    admin_group = ConversationRef(platform, "group", "admin-group")
    features = FeatureService(
        {ordinary_group: frozenset({"help"}), admin_group: frozenset({"admin_notice"})},
        {admin: frozenset({"admin_notice"})},
        frozenset({admin}),
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            actor,
            ordinary_group,
            "private-message-id",
            "private-command-body",
        ),
        mentions_bot=True,
    )
    sender = Mock(
        send_admin_notice=AsyncMock(
            return_value=AdminNoticeSendSummary((admin, admin_group), ())
        )
    )
    notices = AdminNoticeService(features, sender)
    contract = CommandContract(
        id="test.query",
        plugin_id="test",
        section="test",
        examples=(context.text,),
        description="query",
        features_all=("help",),
        category=RequestCategory.OTHER_NETWORK,
    )
    catalog = CommandCatalog()
    catalog.load(
        (PluginContribution(id="test", commands=(contract,)),), known_features=("help",)
    )
    sessions = PortableQuerySessions()
    config = CommandCooldownConfig(
        enabled=True,
        windows=[CommandCooldownWindowConfig(window_seconds=60, max_requests=1)],
    )
    requests = Mock(wraps=InFlightRequestService(features, config))
    cooldown = Mock(wraps=CommandCooldownService(config, features))
    sessions.interactions.request_service = requests
    sessions.interactions.cooldown = cooldown
    side_effect = Mock()

    async def fail() -> OutboundMessage:
        side_effect()
        raise error

    async def continuation() -> PortableReply | None:
        await fail()
        return None

    async def nested() -> PortableReply:
        return PortableReply(OutboundMessage.from_text("nested"), follow_up=fail)

    async def stream() -> AsyncIterator[OutboundMessage]:
        yield OutboundMessage.from_text("partial")
        await fail()

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        assert text == context.text
        if stage == "dispatch":
            await fail()
        return PortableReply(
            OutboundMessage.from_text("initial"),
            follow_up=fail if stage == "follow_up" else None,
            continuation=continuation
            if stage == "continuation"
            else nested
            if stage == "nested"
            else None,
            additional_stream=stream if stage == "stream" else None,
        )

    router = PortableCommandRouter(
        catalog,
        {contract.id: execute},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        admin_notices=notices,
        query_sessions=sessions,
    )
    return SimpleNamespace(
        router=router,
        context=context,
        sender=sender,
        requests=requests,
        cooldown=cooldown,
        admin=admin,
        admin_group=admin_group,
        side_effect=side_effect,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "stage", ["dispatch", "follow_up", "continuation", "nested", "stream"]
)
@pytest.mark.parametrize("notice_failure", [False, True])
async def test_common_error_policy_is_private_and_releases_request(
    platform: Platform,
    stage: str,
    *,
    notice_failure: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime(platform, stage, RuntimeError("sensitive-error-detail"))
    if notice_failure:
        runtime.sender.send_admin_notice.side_effect = ConnectionError(
            "sensitive-notice-error"
        )
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    sent: list[OutboundMessage] = []

    async def send(message: OutboundMessage) -> SendResult:
        sent.append(message)
        return SendResult(delivered=True, message_id=str(len(sent)))

    await deliver_portable_reply(reply, send)
    texts = [
        part.text
        for message in sent
        for part in message.parts
        if isinstance(part, TextPart)
    ]
    assert texts.count(COMMAND_FAILED_MESSAGE) == 1
    assert not sent[-1].request_succeeded
    assert reply.outcome.failed
    runtime.side_effect.assert_called_once()
    runtime.requests.finish.assert_not_called()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.finish.assert_not_called()
    runtime.cooldown.release.assert_called_once()
    notice = runtime.sender.send_admin_notice.await_args
    assert notice is not None
    assert notice.kwargs["private_actors"] == (runtime.admin,)
    assert notice.kwargs["group_conversations"] == (runtime.admin_group,)
    public_and_notice = "\n".join([*texts, str(notice.args[0]), caplog.text])
    for private in (
        "sensitive-error-detail",
        "sensitive-notice-error",
        "private-command-body",
        "private-message-id",
    ):
        assert private not in public_and_notice


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("stage", ["dispatch", "follow_up", "continuation", "stream"])
async def test_cancellation_is_not_replied_to_or_reported(
    platform: Platform, stage: str
) -> None:
    runtime = _runtime(platform, stage, asyncio.CancelledError())
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    with pytest.raises(asyncio.CancelledError):
        reply = await runtime.router.dispatch(runtime.context)
        assert reply is not None
        await deliver_portable_reply(reply, send)
    runtime.sender.send_admin_notice.assert_not_awaited()
    runtime.requests.finish.assert_not_called()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.finish.assert_not_called()
    runtime.cooldown.release.assert_called_once()


@pytest.mark.asyncio
async def test_common_error_notices_are_limited_without_suppressing_error_replies() -> (
    None
):
    runtime = _runtime(
        Platform.ONEBOT, "dispatch", RuntimeError("sensitive-error-detail")
    )
    for _ in range(2):
        reply = await runtime.router.dispatch(runtime.context)
        assert reply is not None
        assert reply.message == OutboundMessage.from_text(
            COMMAND_FAILED_MESSAGE, request_succeeded=False
        )
    runtime.sender.send_admin_notice.assert_awaited_once()
    assert runtime.side_effect.call_count == len(("first", "second"))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_unavailable_data_keeps_existing_reply_without_internal_alert(
    platform: Platform,
) -> None:
    runtime = _runtime(platform, "dispatch", DataUnavailableError())
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    assert reply.message == OutboundMessage.from_text(
        DATABASE_UNAVAILABLE_MESSAGE, request_succeeded=False
    )
    runtime.sender.send_admin_notice.assert_not_awaited()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()


@pytest.mark.asyncio
async def test_admin_notice_timeout_does_not_block_command_failure_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(Platform.ONEBOT, "dispatch", RuntimeError("private"))
    cancelled = asyncio.Event()

    async def wait_forever(*args: object, **kwargs: object) -> None:
        del args, kwargs
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runtime.sender.send_admin_notice.side_effect = wait_forever
    monkeypatch.setattr(
        "ironsbot.services.command_errors._NOTICE_TIMEOUT_SECONDS", 0.01
    )
    reply = await asyncio.wait_for(runtime.router.dispatch(runtime.context), timeout=1)
    assert reply is not None
    assert reply.message == OutboundMessage.from_text(
        COMMAND_FAILED_MESSAGE, request_succeeded=False
    )
    assert cancelled.is_set()
    runtime.sender.send_admin_notice.assert_awaited_once()
