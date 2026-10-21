# SPDX-License-Identifier: MIT
"""Safe phase diagnostics: original exceptions stay chained, signed URLs do not."""

from __future__ import annotations

import logging
import socket
import ssl
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx

from ironsbot.core.delivery_attempt import delivery_unit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class QQDeliveryPhaseError(RuntimeError):
    def __init__(self, phase: str, cause: Exception) -> None:
        self.phase = phase
        chain = exception_chain(cause)
        transport = next(
            (
                item
                for item in chain
                if isinstance(
                    item, (httpx.TransportError, TimeoutError, ConnectionError)
                )
            ),
            None,
        )
        self.transport_failure = transport is not None
        self.original_type = type(transport or cause).__name__
        detail = next(
            (
                item
                for item in chain
                if hasattr(item, "http_status")
                or isinstance(item, httpx.HTTPStatusError)
            ),
            cause,
        )
        response = (
            detail.response if isinstance(detail, httpx.HTTPStatusError) else None
        )
        self.http_status = getattr(detail, "http_status", None) or (
            response.status_code if response is not None else None
        )
        self.api_code = getattr(detail, "api_code", None)
        self.network_errno = next(
            (
                item.errno
                for item in chain
                if isinstance(item, OSError) and isinstance(item.errno, int)
            ),
            None,
        )
        self.failure_category = failure_category(chain, self.http_status)
        self.trace_id = getattr(detail, "trace_id", None) or (
            response.headers.get("x-tps-trace-id")
            or response.headers.get("x-cos-request-id")
            if response is not None
            else None
        )
        super().__init__(
            f"{phase}: {self.original_type}"
            f" (HTTP={self.http_status}, code={self.api_code})"
        )


@asynccontextmanager
async def delivery_phase(phase: str) -> AsyncIterator[None]:
    started = time.monotonic()
    logger.info(
        "QQ delivery phase started: phase=%s unit=%s", phase, delivery_unit.get()
    )
    try:
        yield
    except QQDeliveryPhaseError:
        raise
    except Exception as cause:
        error = QQDeliveryPhaseError(phase, cause)
        # Never interpolate the exception text: httpx errors may contain signed URLs.
        logger.warning(
            "QQ delivery failed: phase=%s exception=%s chain=%s elapsed_ms=%d "
            "http_status=%s api_code=%s trace_id=%s unit=%s category=%s errno=%s",
            phase,
            error.original_type,
            exception_types(cause),
            int((time.monotonic() - started) * 1000),
            error.http_status,
            error.api_code,
            error.trace_id,
            delivery_unit.get(),
            error.failure_category,
            error.network_errno,
        )
        raise error from cause
    else:
        logger.info(
            "QQ delivery phase completed: phase=%s elapsed_ms=%d unit=%s",
            phase,
            int((time.monotonic() - started) * 1000),
            delivery_unit.get(),
        )


def exception_types(error: BaseException) -> str:
    return " <- ".join(type(item).__name__ for item in exception_chain(error))


def failure_category(chain: tuple[BaseException, ...], http_status: int | None) -> str:
    if any(isinstance(item, socket.gaierror) for item in chain):
        return "dns"
    if any(isinstance(item, ssl.SSLError) for item in chain):
        return "tls"
    for item in chain:
        if isinstance(item, httpx.TimeoutException):
            return type(item).__name__
    if any(isinstance(item, TimeoutError) for item in chain):
        return "total_deadline"
    if http_status is not None:
        return "http_or_platform"
    return (
        "transport"
        if any(
            isinstance(item, (httpx.TransportError, ConnectionError)) for item in chain
        )
        else "other"
    )


def exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    causes = []
    visited = set()
    current: BaseException | None = error
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        causes.append(current)
        current = current.__cause__ or current.__context__
    return tuple(causes)
