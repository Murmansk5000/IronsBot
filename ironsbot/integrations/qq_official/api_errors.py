# SPDX-License-Identifier: MIT
"""Structured HTTP errors preserved across the Tencent SDK boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from ironsbot.core.outbound import DeliveryFailureKind, SendResult

if TYPE_CHECKING:
    from collections.abc import Mapping

    from httpx import AsyncClient, Response

_HTTP_CLIENT_ERROR_STATUS = 400
_HTTP_SERVER_ERROR_STATUS = 500
_HTTP_TOO_MANY_REQUESTS_STATUS = 429
_RETRYABLE_API_CODES = frozenset({"40093001"})


class QQOfficialApiError(RuntimeError):
    def __init__(
        self,
        *,
        http_status: int,
        api_code: str,
        message: str,
        trace_id: str | None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.api_code = api_code
        self.trace_id = trace_id


class QQOfficialPartialDeliveryError(RuntimeError):
    """At least one payload was accepted before a later payload failed."""

    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        super().__init__("QQ Official message was only partially delivered")


@dataclass(frozen=True, slots=True)
class QQOfficialHttpClient:
    """Reject failed responses with fields the SDK currently discards."""

    inner: AsyncClient

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
        timeout: float | None = None,
    ) -> Response:
        response = await self.inner.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        if response.status_code < _HTTP_CLIENT_ERROR_STATUS:
            return response
        data = _response_mapping(response)
        api_code = str(data.get("code", response.status_code))
        message = str(data.get("message", "QQ Official API request failed"))
        raise QQOfficialApiError(
            http_status=response.status_code,
            api_code=api_code,
            message=message,
            trace_id=response.headers.get("x-tps-trace-id") or None,
        )


def qq_official_exception_result(error: Exception) -> SendResult:
    if isinstance(error, QQOfficialPartialDeliveryError):
        api_error = _find_api_error(error)
        return SendResult(
            delivered=False,
            message_id=error.message_id,
            error_code=(
                api_error.api_code if api_error is not None else "partial_delivery"
            ),
            error_message=str(error),
            trace_id=api_error.trace_id if api_error is not None else None,
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )

    api_error = _find_api_error(error)
    if api_error is not None:
        return SendResult(
            delivered=False,
            error_code=api_error.api_code,
            error_message=str(api_error),
            trace_id=api_error.trace_id,
            failure_kind=_api_failure_kind(api_error),
        )

    transport_error = _find_transport_error(error)
    if transport_error is not None:
        return SendResult(
            delivered=False,
            error_code=type(transport_error).__name__,
            error_message=str(transport_error),
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )

    return SendResult(
        delivered=False,
        error_code=type(error).__name__,
        error_message=str(error),
        trace_id=getattr(error, "trace_id", None),
        failure_kind=DeliveryFailureKind.RETRYABLE,
    )


def _api_failure_kind(error: QQOfficialApiError) -> DeliveryFailureKind:
    if (
        error.api_code in _RETRYABLE_API_CODES
        or error.http_status == _HTTP_TOO_MANY_REQUESTS_STATUS
    ):
        return DeliveryFailureKind.RETRYABLE
    if error.http_status >= _HTTP_SERVER_ERROR_STATUS:
        return DeliveryFailureKind.RETRYABLE
    return DeliveryFailureKind.PERMANENT


def _find_api_error(error: BaseException) -> QQOfficialApiError | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, QQOfficialApiError):
            return current
        current = current.__cause__
    return None


def _find_transport_error(error: BaseException) -> httpx.TransportError | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, httpx.TransportError):
            return current
        current = current.__cause__
    return None


def _response_mapping(response: Response) -> Mapping[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
