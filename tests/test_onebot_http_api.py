from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ironsbot.integrations.onebot.errors import OneBotActionError, OneBotTransportError
from ironsbot.integrations.onebot.http_api import (
    OneBotHttpApi,
    OneBotHttpRequest,
    OneBotHttpResponse,
)


def _api(exchange: AsyncMock, roots: dict[str, str] | None = None) -> OneBotHttpApi:
    return OneBotHttpApi(
        api_roots=roots if roots is not None else {"1": "http://first/api"},
        access_token="test-token",
        timeout=1,
        request=exchange,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "retcode", "expected"),
    [("ok", 0, {"message_id": 123}), ("async", 1, None)],
)
async def test_http_success_requires_matching_status_and_integer_retcode(
    status: str,
    retcode: int,
    expected: object,
) -> None:
    exchange = AsyncMock(
        return_value=OneBotHttpResponse(
            200,
            json.dumps(
                {"status": status, "retcode": retcode, "data": {"message_id": 123}}
            ),
        )
    )
    assert await _api(exchange).call("1", "send_group_msg", group_id=456) == expected
    exchange.assert_awaited_once()
    request = exchange.call_args.args[0]
    assert request.url == "http://first/api/send_group_msg"
    assert request.headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-token",
    }
    assert json.loads(request.body) == {"group_id": 456}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    [
        None,
        [],
        {},
        {"status": "ok"},
        {"status": "ok", "retcode": True},
        {"status": "ok", "retcode": "0"},
        {"status": "ok", "retcode": 1},
        {"status": "async", "retcode": 0},
        {
            "status": "failed",
            "retcode": 1200,
            "data": {"message_id": 123},
            "wording": "private-marker",
        },
    ],
)
async def test_http_bad_envelopes_never_trust_data_or_provider_wording(
    envelope: Any,
) -> None:
    exchange = AsyncMock(return_value=OneBotHttpResponse(200, json.dumps(envelope)))
    with pytest.raises(OneBotActionError) as caught:
        await _api(exchange).call("1", "send_group_msg")
    assert "private-marker" not in str(caught.value)
    exchange.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content"),
    [
        (500, "private-marker"),
        (302, '{"status":"ok","retcode":0,"data":{"message_id":123}}'),
        (204, None),
        (200, ""),
        (200, "not-json private-marker"),
        (200, b"\xff"),
    ],
)
async def test_http_response_failure_is_uncertain_and_never_retried(
    status: int,
    content: str | bytes | None,
) -> None:
    exchange = AsyncMock(return_value=OneBotHttpResponse(status, content))
    with pytest.raises(OneBotTransportError) as caught:
        await _api(exchange).call("1", "send_group_msg")
    assert not caught.value.definitely_not_sent
    assert "private-marker" not in str(caught.value)
    exchange.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "empty", "closed"])
async def test_missing_root_or_stopped_http_is_definitely_not_sent(mode: str) -> None:
    exchange = AsyncMock()
    api = (
        _api(exchange, {"1": ""} if mode == "empty" else {})
        if mode != "closed"
        else _api(exchange)
    )
    if mode == "closed":
        api.close()
    with pytest.raises(OneBotTransportError) as caught:
        await api.call("1", "send_group_msg")
    assert caught.value.definitely_not_sent
    exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_total_timeout_uses_one_request_and_does_not_serialize_timeout() -> (
    None
):
    entered = asyncio.Event()

    async def request(_request: OneBotHttpRequest) -> OneBotHttpResponse:
        entered.set()
        await asyncio.Event().wait()
        return OneBotHttpResponse(200, "")

    exchange = AsyncMock(side_effect=request)
    timeout = 0.01
    with pytest.raises(OneBotTransportError) as caught:
        await _api(exchange).call("1", "send_group_msg", _timeout=timeout)
    assert entered.is_set() and not caught.value.definitely_not_sent
    exchange.assert_awaited_once()
    assert exchange.call_args.args[0].timeout == timeout
    assert json.loads(exchange.call_args.args[0].body) == {}


@pytest.mark.asyncio
async def test_http_cancellation_after_submit_propagates_without_retry() -> None:
    entered = asyncio.Event()

    async def request(_request: OneBotHttpRequest) -> OneBotHttpResponse:
        entered.set()
        await asyncio.Event().wait()
        return OneBotHttpResponse(200, "")

    exchange = AsyncMock(side_effect=request)
    task = asyncio.create_task(_api(exchange).call("1", "send_group_msg"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    exchange.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_accounts_and_configuration_snapshot_are_isolated() -> None:
    roots = {"1": "http://first/", "2": "http://second/"}
    exchange = AsyncMock(
        return_value=OneBotHttpResponse(200, '{"status":"ok","retcode":0,"data":{}}')
    )
    api = _api(exchange, roots)
    roots["1"] = "http://unexpected/"
    await asyncio.gather(
        api.call("1", "get_login_info"), api.call("2", "get_login_info")
    )
    assert {call.args[0].url for call in exchange.call_args_list} == {
        "http://first/get_login_info",
        "http://second/get_login_info",
    }


def test_http_api_runs_without_nonebot_or_sdk_result_parser() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio, json
from ironsbot.integrations.onebot.http_api import OneBotHttpApi, OneBotHttpResponse
async def request(outgoing):
    assert outgoing.url == 'http://test/send_group_msg'
    assert json.loads(outgoing.body) == {'group_id':456}
    return OneBotHttpResponse(200, json.dumps(
        {'status':'ok','retcode':0,'data':{'message_id':123}}))
async def run():
    api = OneBotHttpApi(api_roots={'1':'http://test/'}, access_token=None,
                       timeout=1, request=request)
    assert await api.call('1', 'send_group_msg', group_id=456) == {'message_id':123}
    api.close()
    assert not any(n.startswith('nonebot.') for n in sys.modules)
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
