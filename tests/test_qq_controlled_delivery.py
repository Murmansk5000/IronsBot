from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from ironsbot.core.delivery_attempt import controlled_delivery, delivery_unit
from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialApiError,
    qq_official_exception_result,
)
from ironsbot.integrations.qq_official.controlled_upload import (
    ControlledMediaUploader,
    _SingleAttemptChunked,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import (
    QQDeliveryPhaseError,
    delivery_phase,
)
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
)
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient
from tests.test_qq_official_sdk_client import _FakeApi, _FakeMedia


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,expected",
    [
        ("upload_prepare", DeliveryFailureKind.RETRYABLE),
        ("cos_put", DeliveryFailureKind.RETRYABLE),
        ("message_submit", DeliveryFailureKind.UNCERTAIN),
    ],
)
async def test_upload_timeout_is_safe_but_submit_timeout_is_not(
    phase: str,
    expected: DeliveryFailureKind,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = delivery_unit.set("dynamic=sample unit=image:2 account=test")
    try:
        with (
            caplog.at_level(logging.WARNING),
            pytest.raises(QQDeliveryPhaseError) as caught,
        ):
            async with delivery_phase(phase):
                raise httpx.ReadTimeout("https://upload.example/?signature=secret")
    finally:
        delivery_unit.reset(token)
    result = qq_official_exception_result(caught.value)
    assert result.failure_kind is expected
    assert caught.value.__cause__ is not None
    assert "ReadTimeout" in caplog.text
    assert "unit=image:2" in caplog.text
    assert "signature" not in caplog.text
    assert "signature" not in (result.error_message or "")


@pytest.mark.asyncio
async def test_controlled_sdk_cos_has_one_put_and_keeps_cause() -> None:
    http = AsyncMock()
    http.put.side_effect = httpx.ConnectTimeout("signed-secret-url")
    uploader = _SingleAttemptChunked(cast("Any", AsyncMock()), http)
    with pytest.raises(QQDeliveryPhaseError) as caught:
        await uploader._put_to_presigned_url(
            "https://cos.example/?secret=key", b"image", 1, 1
        )
    assert caught.value.phase == "cos_put[1/1]"
    assert isinstance(caught.value.__cause__, httpx.ConnectTimeout)
    http.put.assert_awaited_once()


@pytest.mark.asyncio
async def test_controlled_sdk_url_has_one_attempt() -> None:
    api = AsyncMock()
    api.upload_group_file.side_effect = QQOfficialApiError(
        http_status=503, api_code="busy", message="busy", trace_id="trace"
    )
    uploader = ControlledMediaUploader(api, AsyncMock())
    token = controlled_delivery.set(True)
    try:
        with pytest.raises(QQDeliveryPhaseError) as caught:
            await uploader._url_upload_with_retry(
                "group", "test", cast("Any", object())
            )
    finally:
        controlled_delivery.reset(token)
    api.upload_group_file.assert_awaited_once()
    result = qq_official_exception_result(caught.value)
    assert result.trace_id == "trace"
    assert result.failure_kind is DeliveryFailureKind.RETRYABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["group", "c2c"])
async def test_sdk_upload_vs_message_submission_boundary(scope: str) -> None:
    api = _FakeApi()
    media = _FakeMedia(error=httpx.ReadTimeout("secret"))
    client = TencentQQClient(cast("Any", api), cast("Any", media))
    token = controlled_delivery.set(True)
    try:
        with pytest.raises(QQDeliveryPhaseError) as caught:
            await client._send(
                cast("Any", scope),
                "target",
                (QQOfficialImagePayload(content=b"test"),),
                None,
                None,
            )
        assert api.messages == []
        assert (
            qq_official_exception_result(caught.value).failure_kind
            is DeliveryFailureKind.RETRYABLE
        )
        broken_api = AsyncMock()
        broken_api.next_msg_seq = Mock(return_value=1)
        broken_api.post_group_message.side_effect = httpx.ReadTimeout("secret")
        broken_api.post_c2c_message.side_effect = httpx.ReadTimeout("secret")
        broken = TencentQQClient(broken_api, cast("Any", _FakeMedia()))
        with pytest.raises(QQDeliveryPhaseError) as submit:
            await broken._send(
                cast("Any", scope),
                "target",
                (QQOfficialTextPayload("text"),),
                None,
                None,
            )
        assert (
            qq_official_exception_result(submit.value).failure_kind
            is DeliveryFailureKind.UNCERTAIN
        )
    finally:
        controlled_delivery.reset(token)


@pytest.mark.parametrize(
    "status,code,kind",
    [
        (401, "auth", DeliveryFailureKind.PERMANENT),
        (429, "busy", DeliveryFailureKind.RETRYABLE),
        (500, "server", DeliveryFailureKind.RETRYABLE),
        (400, "40093001", DeliveryFailureKind.RETRYABLE),
    ],
)
def test_platform_error_classification(
    status: int, code: str, kind: DeliveryFailureKind
) -> None:
    cause = QQOfficialApiError(
        http_status=status, api_code=code, message="safe", trace_id="trace"
    )
    error = QQDeliveryPhaseError("upload_complete", cause)
    error.__cause__ = cause
    result = qq_official_exception_result(error)
    assert result.failure_kind is kind
    assert result.trace_id == "trace"


@pytest.mark.asyncio
async def test_noncontrolled_call_retains_sdk_retry_policy() -> None:
    api = AsyncMock()
    outcomes = [
        RuntimeError("busy"),
        RuntimeError("busy"),
        {"file_info": "ok"},
    ]
    api.upload_group_file.side_effect = outcomes
    uploader = ControlledMediaUploader(api, AsyncMock())
    uploader._URL_UPLOAD_RETRY_DELAY_BASE = 0
    token = controlled_delivery.set(False)
    try:
        result = await uploader._url_upload_with_retry(
            "group", "target", cast("Any", object())
        )
    finally:
        controlled_delivery.reset(token)
    assert result == {"file_info": "ok"}
    assert api.upload_group_file.await_count == len(outcomes)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["upload_confirm", "upload_complete"])
async def test_confirm_and_complete_have_no_nested_retry(phase: str) -> None:
    api = AsyncMock()
    api.upload_group_part_finish.side_effect = httpx.ReadTimeout("secret")
    api.complete_group_upload.side_effect = httpx.ReadTimeout("secret")
    uploader = _SingleAttemptChunked(api, AsyncMock())
    with pytest.raises(QQDeliveryPhaseError) as caught:
        if phase == "upload_confirm":
            await uploader._part_finish_with_retry(
                "group", "target", "upload", 1, 10, "hash", 120
            )
        else:
            await uploader._complete("group", "target", "upload")
    assert caught.value.phase == phase
    assert (
        sum(
            call.await_count
            for call in (api.upload_group_part_finish, api.complete_group_upload)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_sdk_wrapped_timeout_keeps_original_type_and_retryability() -> None:
    wrapped = RuntimeError("SDK request failed")
    wrapped.__cause__ = httpx.ReadTimeout("signed-secret")
    with pytest.raises(QQDeliveryPhaseError) as caught:
        async with delivery_phase("upload_complete"):
            raise wrapped
    result = qq_official_exception_result(caught.value)
    assert result.error_code == "upload_complete:ReadTimeout"
    assert result.failure_kind is DeliveryFailureKind.RETRYABLE
    assert caught.value.__cause__ is wrapped
