from __future__ import annotations

import asyncio
from dataclasses import replace
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
from ironsbot.core.outbound import (
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
    TextPart,
)
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
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from ironsbot.services.identity_observation import SilentIdentityObservationService


def _runtime(
    platform: Platform,
    stage: str,
    error: BaseException,
    *,
    identity_observer: SilentIdentityObservationService | None = None,
) -> SimpleNamespace:
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

    async def stream() -> AsyncGenerator[OutboundMessage, None]:
        yield OutboundMessage.from_text("partial")
        await fail()

    def fail_receipt() -> None:
        side_effect()
        raise error

    async def closing_stream() -> AsyncGenerator[OutboundMessage, None]:
        try:
            yield OutboundMessage.from_text("partial")
        finally:
            fail_receipt()

    async def successful_follow_up() -> OutboundMessage:
        side_effect()
        return OutboundMessage.from_text("query result")

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        assert text == context.text
        if stage == "dispatch":
            await fail()
        return PortableReply(
            OutboundMessage.from_text("initial"),
            follow_up=fail
            if stage == "follow_up"
            else successful_follow_up
            if stage == "advisory"
            else None,
            continuation=continuation
            if stage == "continuation"
            else nested
            if stage == "nested"
            else None,
            additional_stream=stream
            if stage == "stream"
            else closing_stream
            if stage == "stream_close"
            else None,
            on_delivered=fail_receipt if stage == "receipt" else None,
            on_finished=fail_receipt if stage == "completion" else None,
            on_delivery_failed=fail_receipt if stage == "failed_callback" else None,
            initial_is_advisory=stage == "advisory",
        )

    router = PortableCommandRouter(
        catalog,
        {contract.id: execute},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        admin_notices=notices,
        identity_observer=identity_observer,
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
        sessions=sessions,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "stage",
    ["send", "receipt", "completion", "failed_callback", "stream_close", "on_sent"],
)
@pytest.mark.parametrize("notice_failure", [False, True])
async def test_delivery_exceptions_notify_only_admins_without_retry_or_success_charge(
    platform: Platform,
    stage: str,
    *,
    notice_failure: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = RuntimeError("sensitive-delivery-detail")
    runtime = _runtime(platform, stage, error)
    if notice_failure:
        runtime.sender.send_admin_notice.side_effect = RuntimeError(
            "private-notice-detail"
        )
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    sent: list[OutboundMessage] = []

    async def send(message: OutboundMessage) -> SendResult:
        sent.append(message)
        if stage == "send":
            runtime.side_effect()
            raise error
        if stage == "failed_callback" or (stage == "stream_close" and len(sent) > 1):
            return SendResult(delivered=False, error_code="rejected")
        return SendResult(delivered=True, message_id=str(len(sent)))

    def on_sent(_stage: str, _result: SendResult) -> None:
        if stage == "on_sent":
            runtime.side_effect()
            raise error

    with pytest.raises(RuntimeError, match="sensitive-delivery-detail"):
        await deliver_portable_reply(reply, send, on_sent=on_sent)
    assert len(sent) == (len(("initial", "partial")) if stage == "stream_close" else 1)
    assert all(COMMAND_FAILED_MESSAGE not in str(message.parts) for message in sent)
    runtime.side_effect.assert_called_once()
    runtime.requests.finish.assert_not_called()
    runtime.cooldown.finish.assert_not_called()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()
    notice = runtime.sender.send_admin_notice.await_args
    assert notice is not None
    assert notice.kwargs["private_actors"] == (runtime.admin,)
    assert notice.kwargs["group_conversations"] == (runtime.admin_group,)
    expected_phase = (
        "send"
        if stage == "send"
        else "receipt"
        if stage in {"receipt", "on_sent"}
        else "cleanup"
    )
    assert f"阶段：{expected_phase}" in str(notice.args[0])
    for private in (
        "sensitive-delivery-detail",
        "private-notice-detail",
        "private-command-body",
        "private-message-id",
    ):
        assert private not in str(notice.args[0]) + caplog.text
    # Probe the real services again after cleanup, not just mock release counters.
    admitted = runtime.requests.admit(**runtime.requests.admit.call_args.kwargs)
    assert admitted.allowed
    runtime.requests.release(admitted.token)
    cooldown = runtime.cooldown.admit(**runtime.cooldown.admit.call_args.kwargs)
    assert cooldown.allowed
    runtime.cooldown.release(cooldown.token)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_nested_delivery_error_inherits_the_single_public_alert_handler(
    platform: Platform,
) -> None:
    runtime = _runtime(platform, "nested", RuntimeError("unused business failure"))
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    send = AsyncMock(
        side_effect=[
            SendResult(delivered=True, message_id="initial"),
            RuntimeError("private send detail"),
        ]
    )
    with pytest.raises(RuntimeError, match="private send detail"):
        await deliver_portable_reply(reply, send)
    runtime.sender.send_admin_notice.assert_awaited_once()
    runtime.side_effect.assert_not_called()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()
    runtime.requests.finish.assert_not_called()
    runtime.cooldown.finish.assert_not_called()
    assert send.await_count == len(("initial", "nested"))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_error_handler_failure_preserves_original_delivery_exception(
    platform: Platform,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime(platform, "normal", RuntimeError())
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    reporter = AsyncMock(side_effect=RuntimeError("private reporter detail"))
    send = AsyncMock(side_effect=ConnectionError("private send detail"))
    with pytest.raises(ConnectionError, match="private send detail"):
        await deliver_portable_reply(replace(reply, on_delivery_error=reporter), send)
    reporter.assert_awaited_once()
    assert "private reporter detail" not in caplog.text
    assert "private send detail" not in caplog.text
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_expected_delivery_rejection_is_not_an_exception_alert(
    platform: Platform,
) -> None:
    runtime = _runtime(platform, "normal", RuntimeError())
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    send = AsyncMock(
        return_value=SendResult(delivered=False, error_code="quota_rejected")
    )
    assert not await deliver_portable_reply(reply, send)
    runtime.sender.send_admin_notice.assert_not_awaited()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_advisory_send_exception_alerts_once_but_query_completes(
    platform: Platform,
) -> None:
    runtime = _runtime(platform, "advisory", RuntimeError())
    reply = await runtime.router.dispatch(runtime.context)
    assert reply is not None
    send = AsyncMock(
        side_effect=[
            RuntimeError("private progress failure"),
            SendResult(delivered=True, message_id="result"),
        ]
    )
    assert await deliver_portable_reply(reply, send)
    assert not reply.outcome.failed
    assert [call.args[0] for call in send.await_args_list] == [
        OutboundMessage.from_text("initial"),
        OutboundMessage.from_text("query result"),
    ]
    runtime.sender.send_admin_notice.assert_awaited_once()
    runtime.side_effect.assert_called_once()
    runtime.requests.finish.assert_called_once()
    runtime.cooldown.finish.assert_called_once()
    runtime.requests.release.assert_not_called()
    runtime.cooldown.release.assert_not_called()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("stage", ["send", "receipt", "completion", "menu_receipt"])
async def test_public_execute_contains_delivery_errors_and_releases_request(
    platform: Platform, stage: str, caplog: pytest.LogCaptureFixture
) -> None:
    error = RuntimeError("private-transport-body")
    runtime = _runtime(platform, stage, error)
    if stage == "menu_receipt":
        runtime.sessions.record_delivery = Mock(side_effect=error)
    send = AsyncMock(side_effect=error if stage == "send" else None)
    send.return_value = SendResult(delivered=True, message_id="receipt")

    assert not await runtime.router.execute(runtime.context, send)
    send.assert_awaited_once()
    runtime.sender.send_admin_notice.assert_awaited_once()
    runtime.requests.release.assert_called_once()
    runtime.cooldown.release.assert_called_once()
    runtime.requests.finish.assert_not_called()
    runtime.cooldown.finish.assert_not_called()
    assert "private-transport-body" not in caplog.text
    if stage == "menu_receipt":
        assert "stage=receipt" in caplog.text
    retry = await runtime.router.dispatch(runtime.context)
    assert retry is not None
    assert not await runtime.router.delivery.deliver(
        runtime.context,
        retry,
        AsyncMock(return_value=SendResult(delivered=False, error_code="rejected")),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "outcome", ["accepted", "rejected", "uncertain", "exception", "cancelled"]
)
async def test_shared_delivery_owns_identity_observation_lifetime(
    platform: Platform, outcome: str
) -> None:
    observer = Mock(record_reply=Mock(return_value=42), discard_reply=Mock())
    runtime = _runtime(
        platform, "success", RuntimeError("unused"), identity_observer=observer
    )
    error = (
        RuntimeError("private-send-detail")
        if outcome == "exception"
        else asyncio.CancelledError()
        if outcome == "cancelled"
        else None
    )
    send = AsyncMock(
        return_value=SendResult(
            delivered=outcome == "accepted",
            message_id="receipt",
            error_code=None if outcome == "accepted" else "rejected",
            failure_kind=DeliveryFailureKind.UNCERTAIN
            if outcome == "uncertain"
            else None,
        ),
        side_effect=error,
    )
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await runtime.router.execute(runtime.context, send)
    else:
        assert await runtime.router.execute(runtime.context, send) is (
            outcome == "accepted"
        )
    call = send.await_args
    assert call is not None
    observer.record_reply.assert_called_once_with(runtime.context.message, call.args[0])
    if outcome == "accepted":
        observer.discard_reply.assert_not_called()
        runtime.requests.finish.assert_called_once()
    else:
        observer.discard_reply.assert_called_once_with(42)
        runtime.requests.release.assert_called_once()
        runtime.cooldown.release.assert_called_once()
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unowned_route_hint_does_not_infer_identity() -> None:
    observer = Mock()
    runtime = _runtime(
        Platform.QQ_OFFICIAL,
        "success",
        RuntimeError("unused"),
        identity_observer=observer,
    )
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    assert await runtime.router.delivery.deliver(
        runtime.context,
        PortableReply(OutboundMessage.from_text("hint")),
        send,
        purpose="route_hint",
    )
    observer.record_reply.assert_not_called()
    observer.discard_reply.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("stage", ["recognition", "routing"])
async def test_input_failures_use_shared_admin_policy_without_starting_business(
    platform: Platform,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = RuntimeError("private-input-detail")
    runtime = _runtime(platform, "dispatch", error)
    route = Mock(return_value=True)
    if stage == "recognition":
        monkeypatch.setattr(runtime.router, "recognizes", Mock(side_effect=error))
    else:
        route.side_effect = error
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="error-reply"))
    assert await runtime.router.ingress.handle(runtime.context, send, allows=route)
    runtime.side_effect.assert_not_called()
    runtime.requests.release.assert_not_called()
    runtime.requests.finish.assert_not_called()
    runtime.cooldown.finish.assert_not_called()
    runtime.sender.send_admin_notice.assert_awaited_once()
    send.assert_awaited_once()
    assert COMMAND_FAILED_MESSAGE in str(send.await_args_list[0].args[0].parts)
    assert "private-input-detail" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["union", "explicit", "claimed"])
async def test_identity_preparation_failure_never_executes_business(stage: str) -> None:
    error = RuntimeError("private-identity-detail")
    runtime = _runtime(Platform.QQ_OFFICIAL, "dispatch", error)
    observer = Mock(observe_official_message=AsyncMock(side_effect=error))
    union = Mock(observe=AsyncMock(side_effect=error))
    ingress = replace(
        runtime.router.ingress,
        identity_observer=observer if stage != "union" else None,
        union_identity=union if stage == "union" else None,
    )
    context = replace(runtime.context, mentions_bot=stage != "claimed")
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="error-reply"))
    assert await ingress.handle(context, send)
    runtime.side_effect.assert_not_called()
    runtime.requests.release.assert_not_called()
    runtime.requests.finish.assert_not_called()
    runtime.cooldown.finish.assert_not_called()
    runtime.sender.send_admin_notice.assert_awaited_once()
    send.assert_awaited_once()
    assert COMMAND_FAILED_MESSAGE in str(send.await_args_list[0].args[0].parts)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("target_source", ["mirror", "direct", "quote"])
@pytest.mark.parametrize("allowed", [False, True])
async def test_input_identity_target_and_route_order_is_owned_by_public_layer(
    platform: Platform,
    target_source: str,
    *,
    allowed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(platform, "unused", RuntimeError("unused"))
    order: list[str] = []
    target = ActorRef(
        platform if target_source == "direct" else Platform.ONEBOT, "12345"
    )

    async def observe_union(_message: IncomingMessageRef) -> None:
        order.append("union")

    async def observe_sender(
        _message: IncomingMessageRef, *, explicitly_addressed: bool
    ) -> None:
        assert explicitly_addressed
        order.append("sender")

    async def recover_target(_message: IncomingMessageRef) -> ActorRef:
        order.append("target")
        return target

    observer = Mock(
        observe_official_message=AsyncMock(side_effect=observe_sender),
        missing_member_target=AsyncMock(side_effect=recover_target),
    )
    ingress = replace(
        runtime.router.ingress,
        union_identity=Mock(observe=AsyncMock(side_effect=observe_union)),
        identity_observer=observer,
    )
    context = replace(
        runtime.context,
        message=replace(
            runtime.context.message,
            text="成就榜123456",
            direct_mentions=(target,) if target_source == "direct" else (),
            reply_to_id="quote" if target_source == "quote" else None,
        ),
    )

    def route(prepared: MessageInputContext) -> bool:
        order.append("route")
        expected = (
            (target,)
            if (
                target_source == "direct"
                or (platform is Platform.QQ_OFFICIAL and target_source == "mirror")
            )
            else ()
        )
        assert prepared.member_mentions == expected
        return allowed

    recognizes = Mock(side_effect=lambda _context: order.append("recognition") or True)
    execute = AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("execute"))
    monkeypatch.setattr(runtime.router, "recognizes", recognizes)
    monkeypatch.setattr(runtime.router, "execute", execute)
    send = AsyncMock()
    assert await ingress.handle(context, send, allows=route) is allowed
    expected_order = ["union", "sender"] if platform is Platform.QQ_OFFICIAL else []
    if platform is Platform.QQ_OFFICIAL and target_source == "mirror":
        expected_order.append("target")
    expected_order.append("route")
    if allowed:
        expected_order.extend(("recognition", "execute"))
    assert order == expected_order
    send.assert_not_awaited()
    runtime.sender.send_admin_notice.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_replayed_delivery_does_not_repeat_side_effect_but_fresh_retry_runs(
    platform: Platform, backend: str, tmp_path: Path
) -> None:
    from ironsbot.integrations.storage.inbound_claims import SqliteInboundMessageClaims

    runtime = _runtime(platform, "advisory", RuntimeError("unused"))
    ingress = runtime.router.ingress
    if backend == "sqlite":
        ingress = replace(
            ingress, claims=SqliteInboundMessageClaims(tmp_path / "claims.sqlite")
        )
    send = AsyncMock(return_value=SendResult(delivered=False, error_code="uncertain"))
    assert await ingress.handle(runtime.context, send)
    runtime.side_effect.assert_called_once()
    sends_after_first = send.await_count
    assert await ingress.handle(runtime.context, send)
    assert send.await_count == sends_after_first
    runtime.side_effect.assert_called_once()
    runtime.requests.finish.assert_not_called()
    runtime.requests.release.assert_called_once()
    if backend == "sqlite":
        ingress = replace(
            ingress, claims=SqliteInboundMessageClaims(tmp_path / "claims.sqlite")
        )
        assert await ingress.handle(runtime.context, send)
        assert send.await_count == sends_after_first
    send.return_value = SendResult(delivered=True, message_id="result")
    fresh = replace(
        runtime.context, message=replace(runtime.context.message, message_id="new")
    )
    assert await ingress.handle(fresh, send)
    assert runtime.side_effect.call_count == len(("first", "fresh"))
    runtime.requests.finish.assert_called_once()
    runtime.cooldown.finish.assert_called_once()
    runtime.sender.send_admin_notice.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_claim_storage_failure_is_fail_closed_without_arbitrary_reply(
    platform: Platform, caplog: pytest.LogCaptureFixture
) -> None:
    runtime = _runtime(platform, "dispatch", RuntimeError("unused"))
    ingress = replace(
        runtime.router.ingress,
        claims=Mock(claim=AsyncMock(side_effect=OSError("private-database-detail"))),
    )
    send = AsyncMock()
    assert await ingress.handle(runtime.context, send)
    runtime.side_effect.assert_not_called()
    send.assert_not_awaited()
    runtime.sender.send_admin_notice.assert_awaited_once()
    runtime.requests.finish.assert_not_called()
    runtime.requests.release.assert_not_called()
    assert "private-database-detail" not in caplog.text
