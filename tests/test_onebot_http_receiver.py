from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import subprocess
import sys
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.drivers import Request

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.http_receiver import OneBotHttpReceiver
from tests.test_onebot_native_reverse import _reverse_message_case

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ironsbot.integrations.onebot.self_commands import SelfCommandAdapter

pytest_plugins = ("tests.test_onebot_native_reverse",)
_REQUEST_PAIR_SIZE = 2


def _body(**fields: object) -> str:
    return json.dumps({"self_id": 1, "post_type": "notice", **fields})


def _headers(body: str | bytes, *, account: str = "1") -> dict[str, str]:
    raw = body.encode() if isinstance(body, str) else body
    return {
        "x-self-id": account,
        "x-signature": "sha1=" + hmac.new(b"test-secret", raw, "sha1").hexdigest(),
    }


@pytest.fixture
def receiver() -> SimpleNamespace:
    owner = TaskOwner()
    event = AsyncMock()
    connection = Mock(return_value=Mock(self_id="1"))
    return SimpleNamespace(
        owner=owner,
        event=event,
        connection=connection,
        receiver=OneBotHttpReceiver(
            secret="test-secret",
            spawn=owner.create,
            connection=connection,
            on_event=event,
        ),
    )


@pytest.mark.parametrize(
    ("account", "signature", "status"),
    [
        ("", "valid", 400),
        ("１２", "valid", 400),
        ("1.0", "valid", 400),
        ("1", "", 401),
        ("1", "wrong", 403),
        ("1", "秘密", 403),
    ],
)
def test_http_authentication_rejects_before_connection_or_task(
    receiver: SimpleNamespace, account: str, signature: str, status: int
) -> None:
    body = _body()
    headers = _headers(body, account=account)
    if signature != "valid":
        headers["x-signature"] = signature
    result = receiver.receiver.receive(headers, body)
    assert result.status == status
    receiver.connection.assert_not_called()
    receiver.event.assert_not_called()
    assert not receiver.owner.tasks


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not-json",
        "[]",
        "null",
        '{"post_type": "message"}',
        _body(self_id=2),
        _body(self_id=True),
        _body(post_type=4),
        b"\xff",
    ],
)
def test_http_bad_payload_never_registers_connection(
    receiver: SimpleNamespace, body: str | bytes
) -> None:
    result = receiver.receiver.receive(_headers(body), body)
    assert result.status == HTTPStatus.BAD_REQUEST
    receiver.connection.assert_not_called()
    receiver.event.assert_not_called()
    assert not receiver.owner.tasks


def test_http_missing_signed_body_and_signature_validation_order(
    receiver: SimpleNamespace,
) -> None:
    result = receiver.receiver.receive(_headers(""), None)
    assert (result.status, result.content) == (400, "Missing Content")
    receiver.connection.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("binary", [False, True])
async def test_http_accepts_authenticated_event_once_with_owned_task(
    receiver: SimpleNamespace, *, signed: bool, binary: bool
) -> None:
    body = _body(notice_type="notify")
    body = body.encode() if binary else body
    receiver.receiver.secret = "test-secret" if signed else None
    result = receiver.receiver.receive(_headers(body), body)
    assert result.status == HTTPStatus.NO_CONTENT
    receiver.connection.assert_called_once_with("1")
    await asyncio.gather(*tuple(receiver.owner.tasks))
    receiver.event.assert_awaited_once_with(
        receiver.connection.return_value, json.loads(body)
    )
    await receiver.owner.cancel_all()


def test_http_stopping_rejects_without_creating_coroutine(
    receiver: SimpleNamespace,
) -> None:
    receiver.receiver.close()
    body = _body()
    assert (
        receiver.receiver.receive(_headers(body), body).status
        == HTTPStatus.SERVICE_UNAVAILABLE
    )
    receiver.connection.assert_not_called()
    receiver.event.assert_not_called()


def test_http_task_rejection_closes_created_coroutine(
    receiver: SimpleNamespace,
) -> None:
    rejected: list[Coroutine[Any, Any, Any]] = []

    def reject(coroutine: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        assert name == "onebot.event"
        rejected.append(coroutine)
        message = "owner stopped"
        raise RuntimeError(message)

    receiver.receiver.spawn = reject
    body = _body()
    with pytest.raises(RuntimeError, match="owner stopped"):
        receiver.receiver.receive(_headers(body), body)
    assert len(rejected) == 1
    assert inspect.getcoroutinestate(rejected[0]) == inspect.CORO_CLOSED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source", ["group", "private", "temporary_private", "own_minimal"]
)
@pytest.mark.parametrize("wire_format", ["array", "cq"])
async def test_http_reaches_same_business_and_receipt_without_native_dispatch(
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
    source: str,
    wire_format: str,
) -> None:
    payload, private, own = _reverse_message_case(runtime, adapter, source, wire_format)
    adapter.http_receiver.secret = "test-secret"
    body = json.dumps(payload)
    result = await adapter._handle_http(
        Request(
            "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
        )
    )
    assert result.status_code == HTTPStatus.NO_CONTENT
    await asyncio.wait_for(asyncio.gather(*tuple(adapter.tasks)), timeout=2)
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    sent = runtime.sends[0]
    assert sent["bot"] == "1"
    assert sent["user_id" if private else "group_id"] == (101 if private else 456)
    assert sent["message"][0]["type"] == "reply"
    assert any(part["type"] == "at" for part in sent["message"]) is not (private or own)
    if source == "temporary_private":
        assert "group_id" not in sent
        assert runtime.execute.call_args.args[1].message.group_role is None
    assert len(raw_path.contexts) == 1
    raw_path.sdk_preprocessing.assert_not_awaited()
    raw_path.native_conversion.assert_not_called()
    raw_path.native_dispatch.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_notice_uses_same_injected_notice_port(
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
) -> None:
    body = _body(notice_type="notify", sub_type="poke", target_id=1, user_id=101)
    adapter.http_receiver.secret = "test-secret"
    result = await adapter._handle_http(
        Request(
            "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
        )
    )
    assert result.status_code == HTTPStatus.NO_CONTENT
    await asyncio.gather(*tuple(adapter.tasks))
    assert isinstance(adapter.notices, AsyncMock)
    adapter.notices.assert_awaited_once_with(adapter.bots["1"], json.loads(body))
    raw_path.native_conversion.assert_not_called()
    raw_path.native_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_concurrent_replay_claims_business_once(
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
) -> None:
    payload, _, _ = _reverse_message_case(runtime, adapter, "group", "array")
    adapter.http_receiver.secret = "test-secret"
    body = json.dumps(payload)
    request = Request(
        "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
    )
    first, replay = await asyncio.gather(
        adapter._handle_http(request), adapter._handle_http(request)
    )
    assert first.status_code == replay.status_code == HTTPStatus.NO_CONTENT
    await asyncio.gather(*tuple(adapter.tasks))
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    assert len(adapter.bots) == 1
    assert len(raw_path.contexts) == _REQUEST_PAIR_SIZE
    raw_path.native_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_failure_uses_shared_release_and_management_only_error_details(
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
) -> None:
    payload, _, _ = _reverse_message_case(runtime, adapter, "group", "array")
    adapter.http_receiver.secret = "test-secret"
    runtime.execute.side_effect = RuntimeError("private-marker")
    body = json.dumps(payload)
    await adapter._handle_http(
        Request(
            "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
        )
    )
    await asyncio.gather(*tuple(adapter.tasks))
    assert len(runtime.sends) == 1
    assert "private-marker" not in json.dumps(runtime.sends)
    runtime.notices.send.assert_awaited_once()
    runtime.execute.side_effect = None
    payload["message_id"] += 1
    body = json.dumps(payload)
    await adapter._handle_http(
        Request(
            "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
        )
    )
    await asyncio.gather(*tuple(adapter.tasks))
    assert runtime.execute.await_count == _REQUEST_PAIR_SIZE
    assert len(runtime.sends) == _REQUEST_PAIR_SIZE
    raw_path.native_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_silent_mode_never_executes_business_or_sends(
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
) -> None:
    from dataclasses import replace

    from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages

    adapter.received = OneBotReceivedMessages(
        replace(runtime.admission, messages_enabled=False),
        runtime.router,
        runtime.messenger,
    ).handle
    payload, _, _ = _reverse_message_case(runtime, adapter, "group", "cq")
    adapter.http_receiver.secret = "test-secret"
    body = json.dumps(payload)
    await adapter._handle_http(
        Request(
            "POST", "http://test/onebot/v11/http", headers=_headers(body), content=body
        )
    )
    await asyncio.gather(*tuple(adapter.tasks))
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []
    raw_path.native_dispatch.assert_not_awaited()


def test_http_receiver_import_and_ownership_work_without_nonebot() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
from unittest.mock import Mock
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.http_receiver import OneBotHttpReceiver
async def run():
    owner = TaskOwner()
    accepted = []
    connection = Mock(self_id='1')
    async def event(source, payload):
        assert source is connection
        accepted.append(payload)
    receiver = OneBotHttpReceiver(secret=None, spawn=owner.create,
        connection=lambda _: connection, on_event=event)
    body = b'{"self_id":1,"post_type":"notice","notice_type":"notify"}'
    assert receiver.receive({'x-self-id':'1'}, body).status == 204
    await asyncio.gather(*tuple(owner.tasks))
    assert len(accepted) == 1
    receiver.close()
    assert receiver.receive({'x-self-id':'1'}, body).status == 503
    await owner.cancel_all()
    assert not owner.tasks
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
