from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from httpx import Response

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.onebot.errors import (
    OneBotActionError,
    OneBotTransportError,
)
from ironsbot.integrations.onebot.http_api import OneBotHttpApi
from ironsbot.integrations.onebot.httpx_exchange import HttpxOneBotExchange
from ironsbot.integrations.onebot.receipts import onebot_send_failure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "expected", "retcode", "not_sent"),
    [
        (
            Response(
                200,
                content='{"status":"failed","retcode":1200,"wording":"private-detail"}',
            ),
            OneBotActionError,
            1200,
            False,
        ),
        (
            Response(200, content='{"status":"failed","retcode":true}'),
            OneBotActionError,
            None,
            False,
        ),
        (
            Response(200, content='{"status":"failed","retcode":"1200"}'),
            OneBotActionError,
            None,
            False,
        ),
        (httpx.ConnectError("private-detail"), OneBotTransportError, None, False),
        (None, OneBotTransportError, None, True),
    ],
)
async def test_http_api_normalizes_only_structured_protocol_errors(
    source: Response | Exception | None,
    expected: type[Exception],
    retcode: int | None,
    *,
    not_sent: bool,
) -> None:
    api = (
        AsyncMock(side_effect=source)
        if isinstance(source, Exception)
        else AsyncMock(return_value=source)
    )
    client = Mock(spec=httpx.AsyncClient, request=api)
    transport = OneBotHttpApi(
        api_roots={"1": "http://test/"} if source is not None else {},
        access_token=None,
        timeout=1,
        request=HttpxOneBotExchange(client),
    )
    with pytest.raises(expected) as caught:
        await transport.call("1", "send_group_msg", group_id=456, message=[])
    if source is None:
        api.assert_not_awaited()
    else:
        api.assert_awaited_once()
        assert api.call_args.args == ("POST", "http://test/send_group_msg")
        assert json.loads(api.call_args.kwargs["content"]) == {
            "group_id": 456,
            "message": [],
        }
    error = caught.value
    assert "private-detail" not in str(error)
    assert "private-detail" not in repr(error)
    if isinstance(error, OneBotActionError):
        assert error.retcode == retcode
    else:
        assert isinstance(error, OneBotTransportError)
        assert error.definitely_not_sent is not_sent
        failure = onebot_send_failure(error)
        assert failure.interrupted is not_sent
        assert failure.result.failure_kind is (
            DeliveryFailureKind.TRANSPORT_UNAVAILABLE
            if not_sent
            else DeliveryFailureKind.UNCERTAIN
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [RuntimeError("offline"), asyncio.CancelledError()])
async def test_http_api_does_not_reclassify_unknown_errors_or_cancellation(
    source: BaseException,
) -> None:
    transport = OneBotHttpApi(
        api_roots={"1": "http://test/"},
        access_token=None,
        timeout=1,
        request=HttpxOneBotExchange(
            Mock(spec=httpx.AsyncClient, request=AsyncMock(side_effect=source))
        ),
    )
    with pytest.raises(type(source)) as caught:
        await transport.call("1", "send_group_msg")
    assert caught.value is source


@pytest.mark.parametrize(
    "text", ["账号状态为离线", "1006514", "connection closed", "网络连接异常"]
)
def test_exception_wording_is_not_transport_or_delivery_evidence(text: str) -> None:
    failure = onebot_send_failure(RuntimeError(text))
    assert failure.result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert not failure.interrupted
    assert text not in (failure.result.error_message or "")


def test_failure_classification_does_not_read_exception_text() -> None:
    class UnprintableError(Exception):
        def __str__(self) -> str:
            message = "untrusted error text must not be inspected"
            raise AssertionError(message)

        def __repr__(self) -> str:
            pytest.fail("untrusted error repr must not be inspected")

    assert (
        onebot_send_failure(UnprintableError()).result.failure_kind
        is DeliveryFailureKind.UNCERTAIN
    )


def test_group_probe_and_receipts_work_without_framework() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys, asyncio
sys.modules['nonebot'] = None
from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.errors import OneBotActionError, OneBotTransportError
from ironsbot.integrations.onebot.receipts import onebot_send_failure
from ironsbot.core.outbound import DeliveryFailureKind
class Connection:
    self_id = '1'
    async def call_api(self, api, **data):
        raise OneBotActionError(1200)
assert asyncio.run(OneBotGroupProbe().can_access(Connection(), group_id=456)) is False
uncertain = onebot_send_failure(OneBotTransportError()).result
assert uncertain.failure_kind is DeliveryFailureKind.UNCERTAIN
not_sent = onebot_send_failure(
    OneBotTransportError(definitely_not_sent=True)
).result
assert not_sent.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
