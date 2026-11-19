# SPDX-License-Identifier: MIT
"""Bound read-only metadata connections without hiding transport failures."""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")
CONNECT_BUDGET_SECONDS = 30.0
RETRY_DELAYS = (0.5, 1.0)
MAX_CAUSE_DEPTH = 12


def _causes(error: BaseException) -> list[BaseException]:
    result: list[BaseException] = []
    while error not in result and len(result) < MAX_CAUSE_DEPTH:
        result.append(error)
        following = error.__cause__ or error.__context__
        if following is None:
            break
        error = following
    return result


def request_host(error: httpx.HTTPError) -> str:
    try:
        return error.request.url.host
    except RuntimeError:
        return "unavailable"


def transport_summary(error: httpx.HTTPError) -> str:
    causes = _causes(error)
    reason = "NETWORK_REQUEST_FAILED"
    if any(isinstance(item, ssl.SSLCertVerificationError) for item in causes):
        reason = "TLS_CERTIFICATE_VERIFY_FAILED"
    elif any(isinstance(item, ssl.SSLEOFError) for item in causes):
        reason = "TLS_HANDSHAKE_EOF"
    elif any(isinstance(item, socket.gaierror) for item in causes):
        reason = "DNS_LOOKUP_FAILED"
    elif isinstance(error, httpx.TimeoutException):
        reason = "NETWORK_TIMEOUT"
    elif isinstance(error, httpx.HTTPStatusError):
        reason = f"HTTP_STATUS_{error.response.status_code}"
    chain = " -> ".join(type(item).__name__ for item in causes)
    return (
        f"{type(error).__name__}: {reason}; host={request_host(error)}; cause={chain}"
    )


async def retry_connection(
    operation: Callable[[], Awaitable[_Result]], *, url: str, stage: str
) -> _Result:
    deadline = time.monotonic() + CONNECT_BUDGET_SECONDS
    try:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return await asyncio.wait_for(
                    operation(), timeout=max(0.0, deadline - time.monotonic())
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:  # noqa: PERF203 - bounded I/O retry
                if (
                    attempt == len(RETRY_DELAYS)
                    or any(
                        isinstance(item, ssl.SSLCertVerificationError)
                        for item in _causes(error)
                    )
                    or time.monotonic() + RETRY_DELAYS[attempt] >= deadline
                ):
                    raise
                logger.info(
                    "Data sync connection retry: stage=%s host=%s "
                    "attempt=%d failure=%s",
                    stage,
                    urlsplit(url).hostname,
                    attempt + 2,
                    transport_summary(error),
                )
                await asyncio.sleep(RETRY_DELAYS[attempt])
    except asyncio.TimeoutError as error:
        message = "data request budget exhausted"
        method = "HEAD" if stage == "metadata" else "GET"
        raise httpx.TimeoutException(
            message, request=httpx.Request(method, url)
        ) from error
    message = "unreachable connection retry state"
    raise AssertionError(message)


@asynccontextmanager
async def download_response(
    client: httpx.AsyncClient, url: str
) -> AsyncIterator[httpx.Response]:
    async with AsyncExitStack() as stack:
        response = await retry_connection(
            lambda: stack.enter_async_context(client.stream("GET", url)),
            url=url,
            stage="download_headers",
        )
        # Body reads keep the existing read timeout and are never replayed here.
        yield response
