import asyncio
import socket
import ssl
from collections.abc import AsyncIterator

import httpx
import pytest
from pytest import MonkeyPatch

from ironsbot.integrations.db_sync import transport
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.integrations.db_sync.storage import _fetch_remote_timestamp

URL = "https://example.invalid/data.sha256?signature=private-value"
MAX_ATTEMPTS = 3
RECOVERED_ATTEMPTS = 2


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "RETRY_DELAYS", (0.0, 0.0))


def test_fingerprint_retries_tls_eof_then_checks_success() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < MAX_ATTEMPTS:
            raise httpx.ConnectError("", request=request) from ssl.SSLEOFError(8, "EOF")
        return httpx.Response(200, text="a" * 64)

    async def run() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            getter = DatabaseSync._fingerprint_getter(URL)
            assert getter is not None
            return await getter(client)

    assert asyncio.run(run()) == "a" * 64
    assert attempts == MAX_ATTEMPTS


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_fingerprint_http_failure_is_not_a_fingerprint_or_retried(status: int) -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text="<html>not a checksum</html>")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            getter = DatabaseSync._fingerprint_getter(URL)
            assert getter is not None
            await getter(client)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        asyncio.run(run())
    assert attempts == 1
    summary = transport.transport_summary(caught.value)
    assert f"HTTP_STATUS_{status}" in summary
    assert "private-value" not in summary


def test_retry_exhaustion_preserves_empty_error_root_cause() -> None:
    attempts = 0

    async def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("", request=httpx.Request("GET", URL)) from (
            ssl.SSLEOFError(8, "signed URL must not be logged: " + URL)
        )

    with pytest.raises(httpx.ConnectError) as caught:
        asyncio.run(transport.retry_connection(fail, url=URL, stage="fingerprint"))
    assert attempts == MAX_ATTEMPTS
    summary = transport.transport_summary(caught.value)
    assert "TLS_HANDSHAKE_EOF" in summary
    assert "SSLEOFError" in summary
    assert "host=example.invalid" in summary
    assert "signature" not in summary
    assert "private-value" not in summary


def test_certificate_verification_failure_is_not_retried() -> None:
    attempts = 0

    async def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("") from ssl.SSLCertVerificationError(1, "untrusted")

    with pytest.raises(httpx.ConnectError) as caught:
        asyncio.run(transport.retry_connection(fail, url=URL, stage="fingerprint"))
    assert attempts == 1
    assert "TLS_CERTIFICATE_VERIFY_FAILED" in transport.transport_summary(caught.value)


def test_shared_deadline_exhaustion_does_not_start_another_attempt(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(transport, "CONNECT_BUDGET_SECONDS", 0.01)
    attempts = 0

    async def slow() -> None:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(1)

    with pytest.raises(httpx.TimeoutException):
        asyncio.run(transport.retry_connection(slow, url=URL, stage="fingerprint"))
    assert attempts == 1


def test_cancellation_is_not_retried() -> None:
    attempts = 0

    async def cancelled() -> None:
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(transport.retry_connection(cancelled, url=URL, stage="metadata"))
    assert attempts == 1


def test_metadata_retries_only_connection_failure() -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("")
        return httpx.Response(
            200, headers={"last-modified": "Mon, 22 Jun 2026 12:00:00 GMT"}
        )

    async def run() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _fetch_remote_timestamp(client, URL)

    assert asyncio.run(run()) is not None
    assert attempts == RECOVERED_ATTEMPTS


def test_download_headers_retry_without_replaying_a_partial_body() -> None:
    attempts = 0

    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"partial"
            message = "body interrupted"
            raise httpx.ReadError(message)

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("")
        return httpx.Response(200, stream=BrokenBody())

    async def run() -> None:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
            transport.download_response(client, URL) as response,
        ):
            await response.aread()

    with pytest.raises(httpx.ReadError):
        asyncio.run(run())
    assert attempts == RECOVERED_ATTEMPTS


def test_dns_failure_is_identified_without_exception_arguments() -> None:
    error = httpx.ConnectError("do not log " + URL)
    error.__cause__ = socket.gaierror(-2, "sensitive host")
    summary = transport.transport_summary(error)
    assert "DNS_LOOKUP_FAILED" in summary
    assert "sensitive" not in summary
    assert "private-value" not in summary
