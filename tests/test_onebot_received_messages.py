from __future__ import annotations

import asyncio
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import RedPacketNoticeConfig
from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot.message_envelope import decode_received_message
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.services.messaging.red_packet import RedPacketNoticeService
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

    from pytest import LogCaptureFixture

pytest_plugins = ("tests.test_shared_onebot_ingress",)


def _sent_message(
    text: str, *, user_id: int = 1, minimal: bool = False, message_id: int = 3
) -> dict[str, Any]:
    payload = group_message_event(
        text, user_id=user_id, message_id=message_id
    ).model_dump()
    payload["post_type"] = "message_sent"
    if minimal:
        for field in (
            "font",
            "sender",
            "sub_type",
            "raw_message",
            "original_message",
            "reply",
            "to_me",
            "anonymous",
        ):
            payload.pop(field, None)
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("minimal", [False, True])
@pytest.mark.parametrize("cq", [False, True])
async def test_own_sent_messages_share_public_execution_without_mutating_source(
    runtime: SimpleNamespace, *, minimal: bool, cq: bool
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    admission = replace(runtime.admission, self_commands=policy)
    receiver = OneBotReceivedMessages(admission, runtime.router, runtime.messenger)
    payload = _sent_message("demo 执行", minimal=minimal)
    if cq:
        payload["message"] = "demo 执行"
    before = deepcopy(payload)
    await receiver.handle(runtime.bot, payload)
    runtime.execute.assert_awaited_once()
    context = runtime.execute.call_args.args[1]
    assert context.text == "执行"
    assert context.message.actor.id == context.request_bot_id == "1"
    assert not context.mentions_bot
    assert payload == before
    assert len(runtime.sends) == 1
    assert not any(part["type"] == "at" for part in runtime.sends[0]["message"])


@pytest.mark.asyncio
@pytest.mark.parametrize("minimal", [False, True])
async def test_other_sent_messages_only_observe_without_reply_lookup_or_business(
    runtime: SimpleNamespace, *, minimal: bool
) -> None:
    observer = Mock(observe_onebot=AsyncMock())
    receiver = OneBotReceivedMessages(
        replace(runtime.admission, identity_observer=observer),
        runtime.router,
        runtime.messenger,
    )
    payload = _sent_message("demo 执行", user_id=101, minimal=minimal)
    payload["message"] = "[CQ:reply,id=-12][CQ:at,qq=777]demo 执行"
    connection = Mock(self_id="1", call_api=AsyncMock())
    await receiver.handle(connection, payload)
    observer.observe_onebot.assert_awaited_once()
    assert observer.observe_onebot.call_args.args[0].mentioned_qq_ids == ("777",)
    connection.call_api.assert_not_awaited()
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    ["disabled", "silent", "blacklist", "prefix", "image", "received", "private"],
)
async def test_sent_origin_and_own_command_guards_cannot_be_bypassed(
    runtime: SimpleNamespace, reason: str
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=reason != "disabled", prefixes=["demo "])
    )
    admission = replace(
        runtime.admission, self_commands=policy, messages_enabled=reason != "silent"
    )
    receiver = OneBotReceivedMessages(admission, runtime.router, runtime.messenger)
    payload = _sent_message("执行" if reason == "prefix" else "demo 执行")
    if reason == "blacklist":
        runtime.policies[runtime.group] = frozenset({"blacklist"})
    elif reason == "image":
        payload["message"].append({"type": "image", "data": {"file": "test.png"}})
    elif reason == "received":
        payload["post_type"] = "message"
    elif reason == "private":
        payload["message_type"] = "private"
    await receiver.handle(runtime.bot, payload)
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_own_outbound_echo_is_rejected_before_shared_command_claim(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    monkeypatch.setattr(runtime.messenger, "_self_commands", policy)
    runtime.execute.return_value = OutboundMessage.from_text("demo 执行")
    command_entry = Mock(handle=AsyncMock(wraps=runtime.router.ingress.handle))
    receiver = OneBotReceivedMessages(
        replace(runtime.admission, self_commands=policy),
        Mock(ingress=command_entry),
        runtime.messenger,
    )
    await receiver.handle(runtime.bot, _sent_message("demo 执行", message_id=3))
    await receiver.handle(runtime.bot, _sent_message("demo 执行", message_id=4))
    command_entry.handle.assert_awaited_once()
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1


@pytest.mark.parametrize(
    "field",
    ["time", "self_id", "user_id", "message_id", "message_type", "message", "group_id"],
)
def test_minimal_sent_messages_require_source_identity_and_valid_body(
    field: str, caplog: LogCaptureFixture
) -> None:
    payload = _sent_message("private-marker", minimal=True)
    payload.pop(field)
    assert decode_received_message(payload) is None
    assert "private-marker" not in caplog.text


@pytest.mark.parametrize(
    "field", ["time", "self_id", "user_id", "message_id", "group_id", "font"]
)
def test_sent_integer_fields_reject_boolean_identity(field: str) -> None:
    payload = _sent_message("demo 执行", minimal=True)
    payload[field] = True
    assert decode_received_message(payload) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "silent",
        "user_blacklist",
        "group_blacklist",
        "routing",
        "everyone",
        "account",
        "invalid",
    ],
)
async def test_raw_admission_rejects_without_business_but_preserves_observation(
    runtime: SimpleNamespace, reason: str
) -> None:
    observer = Mock(observe_onebot=AsyncMock())
    admission = replace(runtime.admission, identity_observer=observer)
    payload = group_message_event("执行", user_id=101).model_dump()
    if reason == "silent":
        admission = replace(admission, messages_enabled=False)
    elif reason == "user_blacklist":
        runtime.user_policies[ActorRef(Platform.ONEBOT, "101")] = frozenset(
            {"blacklist"}
        )
    elif reason == "group_blacklist":
        runtime.policies[runtime.group] = frozenset({"blacklist"})
    elif reason == "routing":
        admission = replace(
            admission, routing=Mock(allows_incoming=Mock(return_value=False))
        )
    elif reason == "everyone":
        payload["message"] = "[CQ:at,qq=all]执行"
    elif reason == "account":
        payload["self_id"] = 2
    else:
        payload.pop("font")
    await OneBotReceivedMessages(admission, runtime.router, runtime.messenger).handle(
        runtime.bot, payload
    )
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []
    if reason in {"account", "invalid"}:
        observer.observe_onebot.assert_not_awaited()
    else:
        observer.observe_onebot.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_raw_replay_executes_and_sends_once(
    runtime: SimpleNamespace,
) -> None:
    receiver = OneBotReceivedMessages(
        runtime.admission, runtime.router, runtime.messenger
    )
    payload = group_message_event("执行", user_id=101).model_dump()
    await asyncio.gather(*(receiver.handle(runtime.bot, payload) for _ in range(2)))
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1


@pytest.mark.asyncio
async def test_raw_messages_share_menu_selection_and_cancel(
    runtime: SimpleNamespace,
) -> None:
    receiver = OneBotReceivedMessages(
        runtime.admission, runtime.router, runtime.messenger
    )
    for message_id, text in enumerate(("菜单", "1", "0"), start=1):
        await receiver.handle(
            runtime.bot,
            group_message_event(text, user_id=101, message_id=message_id).model_dump(),
        )
    runtime.select.assert_awaited_once()
    runtime.execute.assert_not_awaited()
    assert len(runtime.sends) == len(("菜单", "1", "0"))


@pytest.mark.asyncio
async def test_raw_business_failure_is_sanitized_and_releases_query_scope(
    runtime: SimpleNamespace,
) -> None:
    receiver = OneBotReceivedMessages(
        runtime.admission, runtime.router, runtime.messenger
    )
    first = group_message_event("执行", user_id=101, message_id=1).model_dump()
    runtime.execute.side_effect = RuntimeError("private-marker")
    await receiver.handle(runtime.bot, first)
    runtime.notices.send.assert_awaited_once()
    assert "private-marker" not in str(runtime.sends)
    await receiver.handle(runtime.bot, first)
    runtime.execute.assert_awaited_once()
    runtime.execute.side_effect = None
    await receiver.handle(
        runtime.bot, group_message_event("执行", user_id=101, message_id=2).model_dump()
    )
    assert runtime.execute.await_count == len(("failure", "success"))
    assert len(runtime.sends) == len(("failure", "success"))
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("command,fails", [(False, False), (True, False), (True, True)])
async def test_raw_passive_notice_runs_only_for_unclaimed_messages(
    runtime: SimpleNamespace, *, command: bool, fails: bool
) -> None:
    order: list[str] = []

    async def query(*_args: object) -> OutboundMessage:
        order.append("query")
        if fails:
            raise RuntimeError
        return OutboundMessage.from_text("result")

    async def notice(*_args: object, **_kwargs: object) -> None:
        order.append("packet")

    runtime.execute.side_effect = query
    notices = Mock(send=AsyncMock(side_effect=notice))
    packets = RedPacketNoticeService(RedPacketNoticeConfig(cooldown_seconds=0), notices)
    connection = Mock(
        self_id="1",
        call_api=AsyncMock(return_value={"group_name": "example", "message_id": 123}),
    )
    receiver = OneBotReceivedMessages(
        runtime.admission,
        runtime.router,
        runtime.messenger,
        red_packets=packets,
    )
    text = "执行" if command else "unknown"
    payload = group_message_event(text, user_id=101).model_dump()
    payload["message"] = [
        {"type": "text", "data": {"text": text}},
        {"type": "redbag", "data": {"title": "packet"}},
    ]
    await receiver.handle(connection, payload)
    assert order == (["query"] if command else ["packet"])
    assert notices.send.await_count == int(not command)


@pytest.mark.parametrize("self_command", [False, True])
def test_raw_socket_to_shared_business_and_receipt_without_nonebot(
    *, self_command: bool
) -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
import json
from unittest.mock import Mock, AsyncMock
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.outbound_limits import GroupOutboundRateLimitService
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.own_commands import OwnAccountCommandPolicy
async def run():
    own = __OWN__
    owner = TaskOwner()
    features = FeatureService(
        {ConversationRef(Platform.ONEBOT,'group','456'):frozenset({'help'})},
        {}, frozenset())
    catalog = CommandCatalog()
    catalog.load((PluginContribution(id='test', commands=(CommandContract(
        id='test.query', plugin_id='test', section='test', examples=('execute',),
        description='query', features_all=('help',), category=RequestCategory.LOCAL,
    ),)),), known_features=('help',))
    calls = []
    async def query(text, context):
        assert text == 'execute' and context.mentions_bot is (not own)
        assert context.message.actor.id == ('1' if own else '101')
        calls.append(context)
        return OutboundMessage.from_text('result')
    router = PortableCommandRouter(catalog, {'test.query':query}, features,
        ai=Mock(chat_reply=AsyncMock()),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService())
    limits = GroupOutboundRateLimitService(
        OutboundRateLimitConfig(enabled=False), features, owner.create)
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=['demo ']))
    admission = OneBotAdmissionService(True, features, self_commands=policy)
    receiver = OneBotReceivedMessages(admission,
        router, OneBotOutboundMessenger(Mock(), limits))
    finished, accepted = asyncio.Event(), asyncio.Event()
    handled, sent = [], []
    class Socket:
        headers = {'x-self-id':'1', 'authorization':'Bearer test-token'}
        def __init__(self):
            self.frames = asyncio.Queue()
        async def accept(self):
            accepted.set()
        async def receive(self):
            raw = await self.frames.get()
            if raw is None:
                raise ConnectionError()
            return raw
        async def send(self, raw):
            request = json.loads(raw)
            assert request['action'] == 'send_group_msg'
            assert request['params']['group_id'] == 456
            parts = request['params']['message']
            assert parts[0] == {'type':'reply','data':{'id':'3'}}
            assert any(part['type'] == 'at' for part in parts) is (not own)
            assert parts[-1] == {'type':'text','data':{'text':'result'}}
            sent.append(request)
            await self.frames.put(json.dumps(dict(echo=request['echo'],
                status='ok', retcode=0, data={'message_id':123})))
        async def close(self, code=1000, reason=''):
            await self.frames.put(None)
    socket = Socket()
    async def dispatch(session, payload):
        await receiver.handle(session, payload)
        handled.append(payload)
        finished.set()
    server = OneBotReverseServer(access_token='test-token', api_timeout=1,
        spawn=owner.create, connected=lambda _:False, on_connect=lambda _:None,
        on_disconnect=lambda _:None, on_event=dispatch)
    serving = asyncio.create_task(server.handle(socket))
    await accepted.wait()
    payload = dict(time=0, self_id=1, post_type='message', message_type='group',
        sub_type='normal', user_id=101, message_id=3, group_id=456, font=0,
        sender={'user_id':101}, message='[CQ:at,qq=1]execute', raw_message='execute')
    if own:
        payload.update(post_type='message_sent', user_id=1, message='demo execute')
        for field in ('font', 'sub_type', 'sender', 'raw_message'):
            payload.pop(field)
    for _ in range(2):
        finished.clear()
        await socket.frames.put(json.dumps(payload))
        await asyncio.wait_for(finished.wait(), timeout=2)
    assert len(handled) == 2 and len(calls) == len(sent) == 1
    assert server.sessions['1'].pending_count == 0
    await server.close()
    await serving
    await owner.cancel_all()
    assert not server.sessions
    assert not any(name.startswith('nonebot.') for name in sys.modules)
asyncio.run(run())
"""
    script = script.replace("__OWN__", repr(self_command))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
