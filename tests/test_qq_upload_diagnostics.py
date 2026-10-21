from __future__ import annotations

import asyncio
import hashlib
import logging
import socket
import ssl
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from qqbot_agent_sdk.dto import UploadPart, UploadPrepareResponse

from ironsbot.core.delivery_attempt import delivery_unit
from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.qq_official.api_errors import qq_official_exception_result
from ironsbot.integrations.qq_official.controlled_upload import (
    COS_PART_DEADLINE_SECONDS,
    COS_PUT_TIMEOUT,
    _SingleAttemptChunked,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import (
    QQDeliveryPhaseError,
    delivery_phase,
)
from ironsbot.integrations.qq_official.media_diagnostics import (
    log_media_metadata,
    log_upload_parts,
)

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_TOTAL_DEADLINE = 300.0


@pytest.mark.asyncio
async def test_cos_logs_safe_host_timeout_status_and_trace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"x-cos-request-id": "test-trace"})

    marker = delivery_unit.set("dynamic=test unit=image:2 round=3")
    try:
        with caplog.at_level(logging.INFO):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                await _SingleAttemptChunked(
                    cast("Any", AsyncMock()), http
                )._put_to_presigned_url(
                    "https://example.test/private-path?signature=secret", b"data", 1, 1
                )
    finally:
        delivery_unit.reset(marker)
    logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("ironsbot.")
    )
    assert "host=example.test" in logs
    assert "connect_timeout=15.0 read_timeout=60.0 write_timeout=60.0" in logs
    assert "pool_timeout=30.0 total_deadline=300.0" in logs
    assert "http_status=200 trace_id=test-trace" in logs
    assert "dynamic=test unit=image:2 round=3" in logs
    assert "private-path" not in logs
    assert "signature" not in logs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cause", "category"),
    [
        (socket.gaierror(-2, "private hostname"), "dns"),
        (ssl.SSLError("private TLS address"), "tls"),
        (httpx.ConnectTimeout("secret"), "ConnectTimeout"),
        (httpx.ReadTimeout("secret"), "ReadTimeout"),
        (httpx.WriteTimeout("secret"), "WriteTimeout"),
        (httpx.PoolTimeout("secret"), "PoolTimeout"),
        (TimeoutError("secret"), "total_deadline"),
        (httpx.ConnectError("secret"), "transport"),
    ],
)
async def test_failure_category_and_chain_are_safe(
    cause: Exception, category: str, caplog: pytest.LogCaptureFixture
) -> None:
    wrapper = RuntimeError("https://example.test/?signature=secret")
    wrapper.__cause__ = cause
    with caplog.at_level(logging.INFO), pytest.raises(QQDeliveryPhaseError) as caught:
        async with delivery_phase("upload_prepare"):
            raise wrapper
    assert caught.value.failure_category == category
    assert caught.value.__cause__ is wrapper
    assert f"category={category}" in caplog.text
    assert f"chain=RuntimeError <- {type(cause).__name__}" in caplog.text
    assert "QQ delivery phase started:" in caplog.text
    assert "signature" not in caplog.text
    assert "private" not in caplog.text
    if isinstance(cause, socket.gaierror):
        assert caught.value.network_errno == cause.errno
        assert "errno=-2" in caplog.text


@pytest.mark.asyncio
async def test_cos_timeout_is_explicit_and_does_not_change_shared_client() -> None:
    recorded = []

    async def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request.extensions["timeout"])
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        uploader = _SingleAttemptChunked(cast("Any", AsyncMock()), http)
        await uploader._put_to_presigned_url(
            "https://example.test/upload", b"data", 1, 1
        )
        assert http.timeout == httpx.Timeout(5.0)
    assert recorded == [{"connect": 15.0, "read": 60.0, "write": 60.0, "pool": 30.0}]


@pytest.mark.asyncio
async def test_cos_total_deadline_remains_300_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []
    original = asyncio.wait_for

    async def wait_for(awaitable: Any, timeout: float) -> Any:
        seen.append(timeout)
        return await original(awaitable, timeout)

    monkeypatch.setattr(
        "ironsbot.integrations.qq_official.controlled_upload.asyncio.wait_for", wait_for
    )
    http = AsyncMock()
    http.put.return_value = httpx.Response(
        200, request=httpx.Request("PUT", "https://example.test/")
    )
    await _SingleAttemptChunked(cast("Any", AsyncMock()), http)._put_to_presigned_url(
        "https://example.test/", b"test", 1, 1
    )
    assert seen == [COS_PART_DEADLINE_SECONDS]
    assert COS_PART_DEADLINE_SECONDS == EXPECTED_TOTAL_DEADLINE
    assert http.put.await_args.kwargs["timeout"] == COS_PUT_TIMEOUT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout],
)
async def test_each_pre_submit_timeout_is_diagnosed_without_url(
    kind: type[httpx.TimeoutException],
) -> None:
    http = AsyncMock()
    http.put.side_effect = kind("https://example.test/?signature=secret")
    with pytest.raises(QQDeliveryPhaseError) as caught:
        await _SingleAttemptChunked(
            cast("Any", AsyncMock()), http
        )._put_to_presigned_url("https://example.test/", b"data", 1, 1)
    result = qq_official_exception_result(caught.value)
    assert result.failure_kind is DeliveryFailureKind.RETRYABLE
    assert kind.__name__ in (result.error_code or "")
    assert "signature" not in (result.error_message or "")
    http.put.assert_awaited_once()


@pytest.mark.parametrize("animated", [False, True])
def test_media_metadata_preserves_original_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, *, animated: bool
) -> None:
    path = tmp_path / ("private-name.gif" if animated else "private-name.png")
    with (
        Image.new("RGB", (20, 30), "red") as first,
        Image.new("RGB", (20, 30), "blue") as second,
    ):
        if animated:
            first.save(path, save_all=True, append_images=[second], duration=100)
        else:
            first.save(path)
    before = hashlib.sha256(path.read_bytes()).digest()
    with caplog.at_level(logging.INFO):
        log_media_metadata(str(path))
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert f"bytes={path.stat().st_size}" in caplog.text
    assert "width=20 height=30" in caplog.text
    assert f"frames={2 if animated else 1}" in caplog.text
    assert "private-name" not in caplog.text


def test_bad_metadata_does_not_raise_or_log_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image; private secret")
    log_media_metadata(str(path))
    assert "metadata unavailable" in caplog.text
    assert "private secret" not in caplog.text


def test_parts_log_actual_final_part_size(caplog: pytest.LogCaptureFixture) -> None:
    prepared = UploadPrepareResponse(
        "private-id",
        10,
        [
            UploadPart(index=1, presigned_url="https://secret"),
            UploadPart(index=2, presigned_url="https://secret"),
        ],
    )
    with caplog.at_level(logging.INFO):
        log_upload_parts(15, prepared)
    assert "parts=2" in caplog.text
    assert "part_sizes=(10, 5)" in caplog.text
    assert "private-id" not in caplog.text
    assert "https://secret" not in caplog.text
