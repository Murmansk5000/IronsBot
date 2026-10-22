from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter as NativeAdapter
from nonebot.adapters.onebot.v11 import Bot
from nonebot.exception import WebSocketClosed

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.integrations.onebot import received_messages as received_protocol
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.http_api import OneBotHttpRequest, OneBotHttpResponse
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.integrations.onebot.transport import OneBotTransport
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import group_message_event, private_message_event

pytest_plugins = ("tests.test_shared_onebot_ingress",)

_POLICY_VIOLATION = 1008

if TYPE_CHECKING:
    from nonebot.drivers import WebSocket

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.ingress_facts import OneBotMessageOrigin
    from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts
    from ironsbot.services.onebot_admission import OneBotAdmissionInput


class Socket:
    def __init__(self, account: str = "1", token: str = "Bearer test-token") -> None:
        self.request = SimpleNamespace(
            headers={"x-self-id": account, "authorization": token}
        )
        self.accepted = asyncio.Event()
        self.incoming: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.close_calls: list[tuple[int, str]] = []

    async def accept(self) -> None:
        self.accepted.set()

    async def receive(self) -> str:
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def send(self, text: str) -> None:
        await self.outgoing.put(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))
        await self.incoming.put(WebSocketClosed(code))


@pytest.fixture
def adapter(
    monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
) -> OneBotTransport:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    messages = OneBotReceivedMessages(
        runtime.admission, runtime.router, runtime.messenger
    )
    owner = TaskOwner()
    result = OneBotTransport(
        driver,
        spawn=owner.create,
        received=messages.handle,
        notices=AsyncMock(),
        request_http=AsyncMock(),
        connections=OneBotConnections(),
        observer=ApplicationLifecycle(task_owner=owner),
    )
    monkeypatch.setattr(result.reverse_server, "access_token", "test-token")
    monkeypatch.setattr(
        driver, "_bot_connect", Mock(side_effect=AssertionError("native bot connected"))
    )
    monkeypatch.setattr(
        driver,
        "_bot_disconnect",
        Mock(side_effect=AssertionError("native bot disconnected")),
    )

    async def http(request: OneBotHttpRequest) -> OneBotHttpResponse:
        params = json.loads(request.body)
        runtime.sends.append({"bot": "1", **params})
        if runtime.transport.error is not None:
            raise runtime.transport.error
        data = runtime.transport.response
        if data is None:
            data = (
                {}
                if runtime.transport.fails
                else {"message_id": len(runtime.sends) + 100}
            )
        return OneBotHttpResponse(
            200, json.dumps({"status": "ok", "retcode": 0, "data": data})
        )

    result.http_api.api_roots["1"] = "http://test/"
    result.http_api.request = http

    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account", "token"),
    [("", "Bearer test-token"), ("１２", "Bearer test-token"), ("1", "wrong")],
)
async def test_invalid_handshake_does_not_register_a_connection(
    adapter: OneBotTransport, account: str, token: str
) -> None:
    socket = Socket(account, token)
    await adapter._handle_ws(cast("WebSocket", socket))
    assert not socket.accepted.is_set()
    assert socket.close_calls[0][0] == _POLICY_VIOLATION
    assert adapter.accounts.snapshot() == ()
    assert adapter.reverse_server.sessions == {}


@pytest.mark.asyncio
async def test_notice_handoff_uses_owned_rpc_and_disconnects_pending_calls(
    adapter: OneBotTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = asyncio.Event()
    handled = AsyncMock(side_effect=lambda *_: received.set())
    monkeypatch.setattr(adapter, "notices", handled)
    socket = Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    try:
        await socket.accepted.wait()
        bot = adapter.accounts.get("1")
        assert bot is not None
        assert bot is adapter.reverse_server.sessions["1"]
        request = asyncio.create_task(
            bot.call_api("send_group_msg", group_id=456)
        )
        sent = await socket.outgoing.get()
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": sent["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": -42},
                }
            )
        )
        assert await request == {"message_id": -42}
        await socket.incoming.put(
            json.dumps(
                {
                    "time": 0,
                    "self_id": 1,
                    "post_type": "notice",
                    "notice_type": "notify",
                    "sub_type": "poke",
                    "user_id": 101,
                    "target_id": 1,
                }
            )
        )
        await asyncio.wait_for(received.wait(), timeout=1)
        assert handled.call_args.args[1]["notice_type"] == "notify"
        pending = asyncio.create_task(bot.call_api("get_login_info"))
        await socket.outgoing.get()
        await socket.close()
        await serving
        with pytest.raises(OneBotTransportError) as caught:
            await pending
        assert not caught.value.definitely_not_sent
        assert adapter.accounts.snapshot() == ()
        assert adapter.reverse_server.sessions == {}
        # Old Bot references remain tied to the closed session, not HTTP or a new bot.
        with pytest.raises(OneBotTransportError) as closed:
            await bot.call_api("send_group_msg")
        assert closed.value.definitely_not_sent
        assert socket.outgoing.empty()
    finally:
        await socket.close()
        await serving
        await asyncio.gather(*adapter.tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_frame", ["[]", "not-json", '{"self_id":2,"post_type":"message"}']
)
async def test_invalid_or_foreign_frame_is_never_dispatched(
    adapter: OneBotTransport, monkeypatch: pytest.MonkeyPatch, bad_frame: str
) -> None:
    handled = AsyncMock()
    monkeypatch.setattr("nonebot.message.handle_event", handled)
    socket = Socket()
    await socket.incoming.put(bad_frame)
    await adapter._handle_ws(cast("WebSocket", socket))
    handled.assert_not_awaited()
    assert adapter.reverse_server.sessions == {}
    assert adapter.accounts.snapshot() == ()


@pytest.mark.asyncio
async def test_duplicate_is_rejected_and_server_shutdown_releases_waiters(
    adapter: OneBotTransport,
) -> None:
    socket, duplicate = Socket(), Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    await socket.accepted.wait()
    await adapter._handle_ws(cast("WebSocket", duplicate))
    assert not duplicate.accepted.is_set()
    bot = adapter.accounts.get("1")
    assert bot is not None
    assert bot is adapter.reverse_server.sessions["1"]
    assert bot is not None
    request = asyncio.create_task(bot.call_api("get_login_info"))
    await socket.outgoing.get()
    await adapter.reverse_server.close()
    await serving
    with pytest.raises(OneBotTransportError):
        await request
    assert adapter.reverse_server.sessions == {}
    assert adapter.accounts.snapshot() == ()


@pytest.fixture
def raw_path(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    contexts: list[MessageInputContext] = []
    project = received_protocol.onebot_admission_input

    def capture(
        facts: OneBotMessageFacts, origin: OneBotMessageOrigin
    ) -> OneBotAdmissionInput:
        incoming = project(facts, origin)
        assert incoming.context is not None
        contexts.append(incoming.context)
        return incoming

    monkeypatch.setattr(received_protocol, "onebot_admission_input", capture)
    sdk_preprocessing = AsyncMock(side_effect=AssertionError("SDK preprocessing used"))
    monkeypatch.setattr(Bot, "handle_event", sdk_preprocessing)
    native_conversion = Mock(side_effect=AssertionError("native event conversion used"))
    monkeypatch.setattr(NativeAdapter, "json_to_event", native_conversion)
    native_dispatch = AsyncMock(side_effect=AssertionError("native dispatch used"))
    monkeypatch.setattr("nonebot.message.handle_event", native_dispatch)
    return SimpleNamespace(
        contexts=contexts,
        sdk_preprocessing=sdk_preprocessing,
        native_conversion=native_conversion,
        native_dispatch=native_dispatch,
    )


def _reverse_message_case(
    runtime: SimpleNamespace,
    adapter: OneBotTransport,
    source: str,
    wire_format: str,
) -> tuple[dict[str, Any], bool, bool]:
    from ironsbot.core.platform import ActorRef, Platform

    private = source in {"private", "temporary_private"}
    own = source.startswith("own_")
    if own:
        policy = OwnAccountCommandPolicy(
            SelfCommandsConfig(enabled=True, prefixes=["demo "])
        )
        adapter.received = OneBotReceivedMessages(
            replace(runtime.admission, self_commands=policy),
            runtime.router,
            runtime.messenger,
        ).handle
    if private:
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = frozenset({"help"})
    event = (
        private_message_event("执行", user_id=101)
        if private
        else group_message_event(
            "demo 执行" if own else "执行", user_id=1 if own else 101
        )
    )
    payload = event.model_dump()
    payload.pop("original_message", None)
    if own:
        payload["post_type"] = "message_sent"
    if source == "own_minimal":
        for field in (
            "font",
            "sender",
            "sub_type",
            "raw_message",
            "reply",
            "to_me",
            "anonymous",
        ):
            payload.pop(field, None)
    if source == "temporary_private":
        payload.update(group_id=456, sub_type="group")
        payload["sender"]["role"] = "owner"
    if wire_format == "cq":
        payload["message"] = (
            "demo 执行" if own else "执行" if private else "[CQ:at,qq=1]执行"
        )
    return payload, private, own


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source", ["group", "private", "temporary_private", "own_full", "own_minimal"]
)
@pytest.mark.parametrize("wire_format", ["array", "cq"])
async def test_reverse_socket_reaches_shared_business_and_receipt_settlement(
    runtime: SimpleNamespace,
    adapter: OneBotTransport,
    raw_path: SimpleNamespace,
    wire_format: str,
    source: str,
) -> None:
    payload, private, own = _reverse_message_case(runtime, adapter, source, wire_format)
    socket = Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    try:
        await socket.accepted.wait()
        await socket.incoming.put(json.dumps(payload))
        sent = await asyncio.wait_for(socket.outgoing.get(), timeout=2)
        assert sent["action"] == ("send_private_msg" if private else "send_group_msg")
        params = sent["params"]
        assert params["user_id" if private else "group_id"] == (101 if private else 456)
        assert params["message"][0]["type"] == "reply"
        assert any(part["type"] == "at" for part in params["message"]) is not (
            private or own
        )
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": sent["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": 123},
                }
            )
        )
        await asyncio.wait_for(asyncio.gather(*tuple(adapter.tasks)), timeout=2)
        runtime.execute.assert_awaited_once()
        raw_path.sdk_preprocessing.assert_not_awaited()
        raw_path.native_conversion.assert_not_called()
        raw_path.native_dispatch.assert_not_awaited()
        context = runtime.execute.call_args.args[1]
        assert len(raw_path.contexts) == 1
        if own:
            assert raw_path.contexts[0].text == "demo 执行"
            assert context.text == "执行"
            assert context.message.actor.id == "1"
        else:
            assert context is raw_path.contexts[0]
        assert context.message.conversation.kind == ("private" if private else "group")
        if source == "temporary_private":
            assert context.message.group_role is None
            assert "group_id" not in params
        runtime.ai.chat_reply.assert_not_awaited()
        # A real reverse session must not fall through to the patched SDK API path.
        assert runtime.sends == []
        assert socket.outgoing.empty()
        session = adapter.reverse_server.sessions["1"]
        assert session.pending_count == 0
    finally:
        await socket.close()
        await serving
        await asyncio.gather(*tuple(adapter.tasks), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_state", ["valid", "malformed", "rejected"])
async def test_reverse_reply_lookup_is_single_and_does_not_import_quoted_targets(
    runtime: SimpleNamespace, adapter: OneBotTransport, reply_state: str
) -> None:
    socket = Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    try:
        await socket.accepted.wait()
        payload = group_message_event("执行", user_id=101).model_dump()
        payload.pop("original_message", None)
        payload["message"] = "[CQ:reply,id=-12][CQ:at,qq=1]执行"
        await socket.incoming.put(json.dumps(payload))
        lookup = await asyncio.wait_for(socket.outgoing.get(), timeout=2)
        assert lookup["action"] == "get_msg"
        assert lookup["params"] == {"message_id": -12}
        reply = {
            "time": 0,
            "message_type": "group",
            "message_id": -12,
            "real_id": -12,
            "sender": {"user_id": 1},
            "message": "[CQ:at,qq=777]quoted-body",
        }
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": lookup["echo"],
                    "status": "failed" if reply_state == "rejected" else "ok",
                    "retcode": 100 if reply_state == "rejected" else 0,
                    "data": {} if reply_state == "malformed" else reply,
                }
            )
        )
        sent = await asyncio.wait_for(socket.outgoing.get(), timeout=2)
        assert sent["action"] == "send_group_msg"
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": sent["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": 123},
                }
            )
        )
        await asyncio.wait_for(asyncio.gather(*tuple(adapter.tasks)), timeout=2)
        runtime.execute.assert_awaited_once()
        context = runtime.execute.call_args.args[1]
        assert context.text == "执行"
        assert context.mentions_bot
        assert not context.member_mentions
        assert context.message.reply_to_id == "-12"
        assert "quoted-body" not in context.text
        assert socket.outgoing.empty()
    finally:
        await socket.close()
        await serving
        await asyncio.gather(*tuple(adapter.tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_temporary_private_cannot_borrow_source_group_permissions(
    runtime: SimpleNamespace,
) -> None:
    event = private_message_event("执行", user_id=101)
    payload = event.model_dump()
    payload.update(group_id=456, sub_type="group")
    payload["sender"]["role"] = "owner"
    await runtime.received.handle(runtime.bot, payload)
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert all("group_id" not in sent for sent in runtime.sends)


@pytest.mark.asyncio
async def test_accepted_event_retains_its_connection_after_immediate_disconnect(
    adapter: OneBotTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    handled = AsyncMock()
    monkeypatch.setattr(adapter, "received", handled)
    socket = Socket()
    await socket.incoming.put(group_message_event("执行").model_dump_json())
    await socket.incoming.put(WebSocketClosed(1000))
    await adapter._handle_ws(cast("WebSocket", socket))
    await asyncio.gather(*tuple(adapter.tasks))
    handled.assert_awaited_once()
    assert handled.call_args.args[1]["post_type"] == "message"
    assert adapter.accounts.snapshot() == ()
    assert adapter.reverse_server.sessions == {}


@pytest.mark.asyncio
async def test_old_bot_cannot_send_using_a_reconnected_accounts_session(
    adapter: OneBotTransport,
) -> None:
    first = Socket()
    old_handler = asyncio.create_task(adapter._handle_ws(cast("WebSocket", first)))
    await first.accepted.wait()
    old_bot = adapter.accounts.get("1")
    assert old_bot is not None
    assert old_bot is adapter.reverse_server.sessions["1"]
    await first.close()
    await old_handler
    second = Socket()
    new_handler = asyncio.create_task(adapter._handle_ws(cast("WebSocket", second)))
    try:
        await second.accepted.wait()
        current = adapter.accounts.get("1")
        assert current is not old_bot
        with pytest.raises(OneBotTransportError) as caught:
            await old_bot.call_api("send_group_msg")
        assert caught.value.definitely_not_sent
        assert second.outgoing.empty()
        assert adapter.accounts.get("1") is current
    finally:
        await second.close()
        await new_handler


@pytest.mark.asyncio
async def test_shutdown_during_accept_never_publishes_a_bot(
    adapter: OneBotTransport,
) -> None:
    release = asyncio.Event()

    class DelayedSocket(Socket):
        async def accept(self) -> None:
            self.accepted.set()
            await release.wait()

    socket = DelayedSocket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    await socket.accepted.wait()
    await adapter.reverse_server.close()
    release.set()
    await serving
    assert adapter.accounts.snapshot() == ()
    assert adapter.reverse_server.sessions == {}
    late = Socket()
    await adapter._handle_ws(cast("WebSocket", late))
    assert not late.accepted.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control",
    [
        {"post_type": "meta_event", "meta_event_type": "heartbeat"},
        {"post_type": "request", "request_type": "friend"},
        {"post_type": "request", "request_type": "group"},
        {"post_type": "custom_provider_event"},
        {"post_type": True},
        {"post_type": None},
    ],
)
async def test_control_frames_do_not_dispatch_native_or_block_the_next_notice(
    adapter: OneBotTransport,
    raw_path: SimpleNamespace,
    control: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed = asyncio.Event()
    notice = AsyncMock(side_effect=lambda *_: observed.set())
    adapter.notices = notice
    socket = Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    try:
        await socket.accepted.wait()
        await socket.incoming.put(
            json.dumps(
                {"self_id": 1, "time": 0, "comment": "private-marker", **control}
            )
        )
        probe = {
            "self_id": 1,
            "time": 0,
            "post_type": "notice",
            "notice_type": "notify",
        }
        await socket.incoming.put(json.dumps(probe))
        await asyncio.wait_for(observed.wait(), timeout=2)
        notice.assert_awaited_once_with(adapter.accounts.get("1"), probe)
        raw_path.native_conversion.assert_not_called()
        raw_path.native_dispatch.assert_not_awaited()
        assert raw_path.contexts == []
        assert "private-marker" not in caplog.text
    finally:
        await socket.close()
        await serving
        await asyncio.gather(*tuple(adapter.tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_during_receive_does_not_dispatch_a_late_frame(
    adapter: OneBotTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading, release = asyncio.Event(), asyncio.Event()
    handled = AsyncMock()
    monkeypatch.setattr(adapter, "received", handled)

    class DelayedSocket(Socket):
        async def receive(self) -> str:
            raw = await super().receive()
            reading.set()
            await release.wait()
            return raw

    socket = DelayedSocket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    await socket.accepted.wait()
    await socket.incoming.put(group_message_event("执行").model_dump_json())
    await reading.wait()
    await adapter.close()
    release.set()
    await serving
    handled.assert_not_awaited()
    assert not adapter.tasks


@pytest.mark.asyncio
async def test_transport_cleanup_survives_connection_observer_failure(
    adapter: OneBotTransport,
) -> None:
    entered, released = asyncio.Event(), asyncio.Event()

    async def pending() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.set()

    task = adapter._spawn_event(pending(), name="onebot.event")
    await entered.wait()
    adapter.observer = Mock(
        bot_connect=AsyncMock(),
        bot_disconnect=AsyncMock(side_effect=RuntimeError("observer failed")),
    )
    connection = adapter._http_connection("1")
    with pytest.raises(RuntimeError, match="observer failed"):
        await adapter.close()
    assert released.is_set() and task.cancelled()
    assert adapter.accounts.snapshot() == ()
    assert not adapter.tasks
    with pytest.raises(OneBotTransportError):
        await connection.call_api("get_login_info")
