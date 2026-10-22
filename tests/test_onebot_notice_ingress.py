from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any, TypeVar, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.features import HelpConfig
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.notice_events import decode_notice
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.services.command_errors import CommandErrorReporter
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)
from ironsbot.services.messaging.poke_reply import PokeReplyService
from tests.test_onebot_native_reverse import Socket

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from types import SimpleNamespace

    from nonebot.drivers import WebSocket
    from pytest import LogCaptureFixture

    from ironsbot.integrations.onebot.transport import OneBotTransport

pytest_plugins = ("tests.test_onebot_native_reverse",)
T = TypeVar("T")


def _poke(**fields: object) -> dict[str, Any]:
    return {
        "time": 0,
        "self_id": 1,
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "group_id": 456,
        "user_id": 101,
        "target_id": 1,
        **fields,
    }


@pytest.mark.parametrize("field", ["time", "self_id", "post_type", "notice_type"])
def test_notice_required_fields_reject_without_logging_payload(
    field: str, caplog: LogCaptureFixture
) -> None:
    payload = _poke(secret="private-marker")
    payload.pop(field)
    assert decode_notice(payload) is None
    assert "invalid envelope" in caplog.text
    assert "private-marker" not in caplog.text


@pytest.mark.parametrize(
    "field", ["time", "self_id", "group_id", "user_id", "target_id", "operator_id"]
)
def test_notice_identity_fields_reject_boolean_coercion(field: str) -> None:
    assert decode_notice(_poke(**{field: True})) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["silent", "account", "target", "uninstalled"])
async def test_unadmitted_or_unowned_poke_has_no_lookup_or_send(
    runtime: SimpleNamespace, reason: str
) -> None:
    poke = Mock(handle=AsyncMock())
    ingress = OneBotNoticeIngress(
        replace(runtime.admission, messages_enabled=reason != "silent"),
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        poke=None if reason == "uninstalled" else poke,
        spawn=asyncio.create_task,
    )
    payload = _poke()
    if reason == "account":
        payload["self_id"] = 2
    elif reason == "target":
        payload["target_id"] = 2
    connection = Mock(self_id="1", call_api=AsyncMock())
    await ingress.handle(connection, payload)
    poke.handle.assert_not_awaited()
    connection.call_api.assert_not_awaited()
    runtime.execute.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
@pytest.mark.parametrize("packet_first", [False, True])
async def test_poke_blocks_only_later_notice_handlers(
    runtime: SimpleNamespace, *, packet_first: bool
) -> None:
    order: list[str] = []

    async def poke(*_args: object, **_kwargs: object) -> None:
        order.append("poke")

    async def packet(*_args: object, **_kwargs: object) -> None:
        order.append("packet")

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(
            poke_reply=5 if packet_first else 0,
            red_packet_notice=0 if packet_first else 5,
        ),
        poke=Mock(handle=AsyncMock(side_effect=poke)),
        red_packets=Mock(handle=AsyncMock(side_effect=packet)),
        spawn=asyncio.create_task,
    )
    await ingress.handle(runtime.bot, _poke(marker="红包"))
    assert order == (["packet", "poke"] if packet_first else ["poke"])


@pytest.mark.asyncio
async def test_same_priority_notice_handlers_are_awaited_concurrently(
    runtime: SimpleNamespace,
) -> None:
    poke_started, packet_started = asyncio.Event(), asyncio.Event()

    async def poke(*_args: object, **_kwargs: object) -> None:
        poke_started.set()
        await packet_started.wait()

    async def packet(*_args: object, **_kwargs: object) -> None:
        packet_started.set()
        await poke_started.wait()

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(poke_reply=0, red_packet_notice=0),
        poke=Mock(handle=AsyncMock(side_effect=poke)),
        red_packets=Mock(handle=AsyncMock(side_effect=packet)),
        spawn=asyncio.create_task,
    )
    await asyncio.wait_for(ingress.handle(runtime.bot, _poke(marker="红包")), timeout=1)
    assert poke_started.is_set() and packet_started.is_set()


@pytest.mark.asyncio
async def test_notice_failure_reports_only_to_admins_without_fake_message(
    runtime: SimpleNamespace, caplog: LogCaptureFixture
) -> None:
    admin = ActorRef(Platform.ONEBOT, "303")
    group = ConversationRef(Platform.ONEBOT, "group", "204")
    features = FeatureService(
        {group: frozenset({"admin_notice"})},
        {admin: frozenset({"admin_notice"})},
        frozenset(),
    )
    sender = Mock(
        send_admin_notice=AsyncMock(
            return_value=AdminNoticeSendSummary((admin, group), ())
        )
    )
    errors = CommandErrorReporter(AdminNoticeService(features, sender))
    ingress = OneBotNoticeIngress(
        replace(runtime.admission, errors=errors),
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        poke=Mock(handle=AsyncMock(side_effect=RuntimeError("private-marker"))),
        spawn=asyncio.create_task,
    )
    await ingress.handle(runtime.bot, _poke())
    await ingress.handle(runtime.bot, _poke())
    sender.send_admin_notice.assert_awaited_once()
    kwargs = sender.send_admin_notice.call_args.kwargs
    assert kwargs["private_actors"] == (admin,)
    assert kwargs["group_conversations"] == (group,)
    assert kwargs["subscription_key"] == "command_error_notice"
    text = sender.send_admin_notice.call_args.args[0].parts[0].text
    assert "notice" in text and "private-marker" not in text
    assert "private-marker" not in caplog.text
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_notice_cancellation_is_not_reported_or_retried(
    runtime: SimpleNamespace,
) -> None:
    service = Mock(handle=AsyncMock(side_effect=asyncio.CancelledError))
    ingress = OneBotNoticeIngress(
        replace(runtime.admission, errors=runtime.errors),
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        poke=service,
        spawn=asyncio.create_task,
    )
    with pytest.raises(asyncio.CancelledError):
        await ingress.handle(runtime.bot, _poke())
    service.handle.assert_awaited_once()
    runtime.notices.send.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_cancelled_notice_handler_cancels_and_drains_its_sibling(
    runtime: SimpleNamespace,
) -> None:
    started, cleaned = asyncio.Event(), asyncio.Event()
    siblings: list[asyncio.Task[Any]] = []

    async def poke(*_args: object, **_kwargs: object) -> None:
        await started.wait()
        raise asyncio.CancelledError

    async def packet(*_args: object, **_kwargs: object) -> None:
        task = asyncio.current_task()
        assert task is not None
        siblings.append(task)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(poke_reply=0, red_packet_notice=0),
        poke=Mock(handle=AsyncMock(side_effect=poke)),
        red_packets=Mock(handle=AsyncMock(side_effect=packet)),
        spawn=asyncio.create_task,
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(
                ingress.handle(runtime.bot, _poke(marker="红包")), timeout=2
            )
        assert cleaned.is_set()
        assert all(task.done() for task in siblings)
        assert runtime.sends == []
        runtime.notices.send.assert_not_awaited()
    finally:
        for task in siblings:
            task.cancel()
        await asyncio.gather(*siblings, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_notice_cancellation_waits_for_owned_cleanup(
    runtime: SimpleNamespace,
) -> None:
    owner = TaskOwner()
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def poke(*_args: object, **_kwargs: object) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        spawn=owner.create,
        poke=Mock(handle=AsyncMock(side_effect=poke)),
    )
    handling = asyncio.create_task(ingress.handle(runtime.bot, _poke()))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert len(owner.tasks) == 1
        handling.cancel()
        await asyncio.wait_for(cleaning.wait(), timeout=2)
        handling.cancel()
        await asyncio.sleep(0)
        assert not handling.done()
        assert len(owner.tasks) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(handling, timeout=2)
        assert owner.tasks == set()
        runtime.notices.send.assert_not_awaited()
    finally:
        release.set()
        handling.cancel()
        await asyncio.gather(handling, return_exceptions=True)
        await owner.cancel_all()


@pytest.mark.asyncio
async def test_notice_spawn_failure_closes_coroutine_and_drains_accepted_tasks(
    runtime: SimpleNamespace,
) -> None:
    owner = TaskOwner()
    submitted: list[Coroutine[Any, Any, Any]] = []
    accepted: list[asyncio.Task[Any]] = []

    def spawn(coroutine: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
        submitted.append(coroutine)
        if accepted:
            raise RuntimeError
        task = owner.create(coroutine, name=name)
        accepted.append(task)
        return task

    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(poke_reply=0, red_packet_notice=0),
        spawn=spawn,
        poke=Mock(handle=AsyncMock()),
        red_packets=Mock(handle=AsyncMock()),
    )
    with pytest.raises(RuntimeError):
        await ingress.handle(runtime.bot, _poke(marker="红包"))
    assert len(accepted) == 1 and accepted[0].cancelled()
    with pytest.raises(RuntimeError, match="cannot reuse already awaited coroutine"):
        submitted[1].send(None)
    assert owner.tasks == set()
    assert runtime.sends == []
    runtime.notices.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_reverse_poke_uses_real_shared_send_and_receipts_without_native_dispatch(
    runtime: SimpleNamespace, adapter: OneBotTransport, raw_path: SimpleNamespace
) -> None:
    ingress = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        poke=PokeReplyService(HelpConfig()),
        spawn=asyncio.create_task,
    )
    adapter.notices = ingress.handle
    socket = Socket()
    serving = asyncio.create_task(adapter._handle_ws(cast("WebSocket", socket)))
    try:
        await socket.accepted.wait()
        await socket.incoming.put(json.dumps(_poke()))
        lookup = await asyncio.wait_for(socket.outgoing.get(), timeout=2)
        assert lookup["action"] == "get_group_member_info"
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": lookup["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": {"role": "admin"},
                }
            )
        )
        sent = await asyncio.wait_for(socket.outgoing.get(), timeout=2)
        assert sent["action"] == "send_group_msg"
        assert {"type": "at", "data": {"qq": "101"}} in sent["params"]["message"]
        assert not any(part["type"] == "reply" for part in sent["params"]["message"])
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
        raw_path.native_conversion.assert_not_called()
        raw_path.native_dispatch.assert_not_awaited()
        raw_path.sdk_preprocessing.assert_not_awaited()
        assert raw_path.contexts == []
        assert adapter.reverse_server.sessions["1"].pending_count == 0
        runtime.execute.assert_not_awaited()
        runtime.ai.chat_reply.assert_not_awaited()
    finally:
        await socket.close()
        await serving
        await asyncio.gather(*tuple(adapter.tasks), return_exceptions=True)


def test_notice_socket_and_shared_poke_delivery_run_without_nonebot() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
import json
from unittest.mock import Mock
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.features import HelpConfig
from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer
from ironsbot.services.messaging.outbound_limits import GroupOutboundRateLimitService
from ironsbot.services.messaging.poke_reply import PokeReplyService
from ironsbot.services.onebot_admission import OneBotAdmissionService
async def run():
    owner = TaskOwner()
    features = FeatureService({}, {}, frozenset())
    limits = GroupOutboundRateLimitService(
        OutboundRateLimitConfig(enabled=False), features, owner.create)
    ingress = OneBotNoticeIngress(OneBotAdmissionService(True, features),
        OneBotOutboundMessenger(Mock(), limits), Mock(), MatcherPriorityConfig(),
        poke=PokeReplyService(HelpConfig(hint_max_per_window=1)), spawn=owner.create)
    accepted, handled = asyncio.Event(), asyncio.Event()
    actions = []
    class Socket:
        headers = {'x-self-id':'1', 'authorization':'Bearer test-token'}
        def __init__(self):
            self.frames = asyncio.Queue()
        async def accept(self):
            accepted.set()
        async def receive(self):
            item = await self.frames.get()
            if item is None:
                raise ConnectionError()
            return item
        async def send(self, raw):
            request = json.loads(raw)
            api, params = request['action'], request['params']
            actions.append(api)
            if api == 'get_group_member_info':
                assert params == {'group_id':456, 'user_id':101, 'no_cache':True}
                data = {'role':'admin'}
            else:
                assert api == 'send_group_msg' and params['group_id'] == 456
                assert {'type':'at', 'data':{'qq':'101'}} in params['message']
                assert not any(part['type'] == 'reply' for part in params['message'])
                data = {'message_id':123}
            await self.frames.put(json.dumps(dict(echo=request['echo'],
                status='ok', retcode=0, data=data)))
        async def close(self, code=1000, reason=''):
            await self.frames.put(None)
    socket = Socket()
    async def dispatch(session, payload):
        await ingress.handle(session, payload)
        handled.set()
    server = OneBotReverseServer(access_token='test-token', api_timeout=1,
        spawn=owner.create, connected=lambda _:False, on_connect=lambda _:None,
        on_disconnect=lambda _:None, on_event=dispatch)
    serving = asyncio.create_task(server.handle(socket))
    await accepted.wait()
    payload = dict(time=0, self_id=1, post_type='notice', notice_type='notify',
        sub_type='poke', group_id=456, user_id=101, target_id=1)
    for _ in range(2):
        handled.clear()
        await socket.frames.put(json.dumps(payload))
        await asyncio.wait_for(handled.wait(), timeout=2)
    assert actions == ['get_group_member_info', 'send_group_msg']
    assert server.sessions['1'].pending_count == 0
    await server.close()
    await serving
    await owner.cancel_all()
    assert not server.sessions
    assert not any(name.startswith('nonebot.') for name in sys.modules)
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
