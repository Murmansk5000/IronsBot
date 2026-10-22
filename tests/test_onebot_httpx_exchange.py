from __future__ import annotations

import json
import subprocess
import sys

import httpx
import pytest

from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.http_api import OneBotHttpApi, OneBotHttpRequest
from ironsbot.integrations.onebot.httpx_exchange import HttpxOneBotExchange


@pytest.mark.asyncio
async def test_exchange_borrows_owned_client_and_preserves_http_request_options() -> (
    None
):
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/send_group_msg":
            return httpx.Response(307, headers={"Location": "/api/send_group_msg"})
        return httpx.Response(
            200, json={"status": "ok", "retcode": 0, "data": {"message_id": 42}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        api = OneBotHttpApi(
            api_roots={"1": "https://onebot.test/"},
            access_token="test-token",
            timeout=2,
            request=HttpxOneBotExchange(client),
        )
        assert await api.call("1", "send_group_msg", group_id=456, message=[]) == {
            "message_id": 42
        }
        assert [request.url.path for request in requests] == [
            "/send_group_msg", "/api/send_group_msg"
        ]
        for request in requests:
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Bearer test-token"
            assert request.headers["Content-Type"] == "application/json"
            assert json.loads(request.content) == {"group_id": 456, "message": []}
            assert request.extensions["timeout"] == dict.fromkeys(
                ("connect", "read", "write", "pool"), 2
            )
        api.close()
        assert not client.is_closed
        await client.get("https://onebot.test/other-application-use")
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [OSError("private-detail"), httpx.ConnectError("private-detail")]
)
async def test_submitted_network_errors_are_uncertain_and_sanitized(
    failure: Exception,
) -> None:
    async def fail(_request: httpx.Request) -> httpx.Response:
        raise failure

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        exchange = HttpxOneBotExchange(client)
        with pytest.raises(OneBotTransportError) as caught:
            await exchange(OneBotHttpRequest("https://onebot.test/", "{}", {}, 1))
    assert not caught.value.definitely_not_sent
    assert "private-detail" not in repr(caught.value)


def test_actual_http_exchange_runs_without_nonebot() -> None:
    script = r"""
import asyncio, sys
sys.modules["nonebot"] = None
import httpx
from ironsbot.integrations.onebot.http_api import OneBotHttpApi
from ironsbot.integrations.onebot.httpx_exchange import HttpxOneBotExchange
async def run():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={
            "status": "ok", "retcode": 0, "data": {"message_id": 1},
        })
    )) as client:
        api = OneBotHttpApi(api_roots={"1": "https://onebot.test"},
            access_token=None, timeout=1, request=HttpxOneBotExchange(client))
        assert await api.call("1", "send_group_msg") == {"message_id": 1}
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
