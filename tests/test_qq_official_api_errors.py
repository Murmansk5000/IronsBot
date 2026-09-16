from __future__ import annotations

import httpx
import pytest

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialApiError,
    QQOfficialHttpClient,
    qq_official_exception_result,
)

_HTTP_TOO_MANY_REQUESTS_STATUS = 429


@pytest.mark.asyncio
async def test_http_boundary_preserves_api_code_status_and_trace() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            _HTTP_TOO_MANY_REQUESTS_STATUS,
            json={"code": 40034100, "message": "quota exceeded"},
            headers={"x-tps-trace-id": "trace-1"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as inner:
        client = QQOfficialHttpClient(inner)
        with pytest.raises(QQOfficialApiError) as raised:
            await client.request("POST", "https://example.test/messages")

    error = raised.value
    assert error.http_status == _HTTP_TOO_MANY_REQUESTS_STATUS
    assert error.api_code == "40034100"
    assert error.trace_id == "trace-1"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (
            QQOfficialApiError(
                http_status=400,
                api_code="40034128",
                message="passive limit",
                trace_id="trace-permanent",
            ),
            DeliveryFailureKind.PERMANENT,
        ),
        (
            QQOfficialApiError(
                http_status=500,
                api_code="50055002",
                message="temporary failure",
                trace_id="trace-retry",
            ),
            DeliveryFailureKind.RETRYABLE,
        ),
        (
            httpx.ConnectTimeout("uncertain"),
            DeliveryFailureKind.UNCERTAIN,
        ),
    ],
)
def test_exception_classification_uses_typed_fields(
    error: Exception,
    kind: DeliveryFailureKind,
) -> None:
    result = qq_official_exception_result(error)

    assert not result.delivered
    assert result.failure_kind is kind


def test_wrapped_api_error_preserves_structured_failure_fields() -> None:
    api_error = QQOfficialApiError(
        http_status=400,
        api_code="11255",
        message="target unavailable",
        trace_id="trace-wrapped",
    )
    sdk_error = RuntimeError()
    sdk_error.__cause__ = api_error
    result = qq_official_exception_result(sdk_error)

    assert not result.delivered
    assert result.error_code == "11255"
    assert result.error_message == "target unavailable"
    assert result.trace_id == "trace-wrapped"
    assert result.failure_kind is DeliveryFailureKind.PERMANENT
