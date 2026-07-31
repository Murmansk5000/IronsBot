from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.operations import HeadlessConfig
from ironsbot.services.operations.headless_session import HeadlessSessionFactory

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessGame, HeadlessLoginRequest


USER_ID = 7654321
REQUEST_INTERVAL_SECONDS = 0.5
LOGIN_FAILURE_MESSAGE = "login failed"


class _Game:
    is_logged_in = True
    user_id = USER_ID


class _Client:
    def __init__(self) -> None:
        self.request: HeadlessLoginRequest | None = None
        self.shutdown_calls = 0

    def get_client(self) -> HeadlessGame:
        return cast("HeadlessGame", _Game())

    async def login(self, request: HeadlessLoginRequest) -> HeadlessGame:
        self.request = request
        return cast("HeadlessGame", _Game())

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FailingClient(_Client):
    async def login(self, request: HeadlessLoginRequest) -> HeadlessGame:
        del request
        raise RuntimeError(LOGIN_FAILURE_MESSAGE)


def test_dedicated_session_uses_isolated_client_and_never_reconnects() -> None:
    client = _Client()
    factory = HeadlessSessionFactory(
        lambda: client,
        HeadlessConfig(
            login_server_addr="https://example.invalid/login.txt",
            heartbeat_interval=120.0,
            request_timeout_seconds=7.0,
            reconnect_retries=-1,
            reconnect_delay=2.0,
            reconnect_delay_max=9.0,
        ),
        request_interval_seconds=REQUEST_INTERVAL_SECONDS,
    )

    async def run() -> None:
        async with factory.open(user_id=USER_ID, password="secret") as game:
            assert game.user_id == USER_ID

    asyncio.run(run())

    assert client.shutdown_calls == 1
    request = client.request
    assert request is not None
    assert request.user_id == USER_ID
    assert request.password == "secret"
    assert request.reconnect_retries == 0
    assert request.request_interval_seconds == REQUEST_INTERVAL_SECONDS


def test_dedicated_session_disconnects_after_login_failure() -> None:
    client = _FailingClient()
    factory = HeadlessSessionFactory(lambda: client, HeadlessConfig())

    async def run() -> None:
        try:
            async with factory.open(user_id=USER_ID, password="secret"):
                raise AssertionError("unreachable")
        except RuntimeError as error:
            assert str(error) == LOGIN_FAILURE_MESSAGE

    asyncio.run(run())
    assert client.shutdown_calls == 1
