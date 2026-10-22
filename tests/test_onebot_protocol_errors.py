from __future__ import annotations

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot
from nonebot.adapters.onebot.v11.exception import (
    ActionFailed,
    ApiNotAvailable,
    NetworkError,
)

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.onebot.errors import (
    OneBotActionError,
    OneBotTransportError,
)
from ironsbot.integrations.onebot.receipts import onebot_send_failure
from ironsbot.integrations.onebot.self_commands import SelfCommandAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "expected", "retcode", "not_sent"),
    [
        (
            ActionFailed(retcode=1200, wording="private-detail"),
            OneBotActionError,
            1200,
            False,
        ),
        (ActionFailed(retcode=True), OneBotActionError, None, False),
        (ActionFailed(retcode="1200"), OneBotActionError, None, False),
        (NetworkError("private-detail"), OneBotTransportError, None, False),
        (ApiNotAvailable(), OneBotTransportError, None, True),
    ],
)
async def test_native_api_normalizes_only_structured_protocol_errors(
    monkeypatch: pytest.MonkeyPatch,
    source: Exception,
    expected: type[Exception],
    retcode: int | None,
    *,
    not_sent: bool,
) -> None:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    api = AsyncMock(side_effect=source)
    monkeypatch.setattr(Adapter, "_call_api", api)
    adapter = SelfCommandAdapter(driver, spawn=TaskOwner().create)
    bot = Bot(adapter, "1")
    with pytest.raises(expected) as caught:
        await adapter._call_api(bot, "send_group_msg", group_id=456, message=[])
    api.assert_awaited_once_with(bot, "send_group_msg", group_id=456, message=[])
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
async def test_native_api_does_not_reclassify_unknown_errors_or_cancellation(
    monkeypatch: pytest.MonkeyPatch, source: BaseException
) -> None:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    monkeypatch.setattr(Adapter, "_call_api", AsyncMock(side_effect=source))
    adapter = SelfCommandAdapter(driver, spawn=TaskOwner().create)
    with pytest.raises(type(source)) as caught:
        await adapter._call_api(Bot(adapter, "1"), "send_group_msg")
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
