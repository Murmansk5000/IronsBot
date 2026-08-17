from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.headless_seer import game as game_module
from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.core.listener import EventListener
from ironsbot.integrations.headless_seer.game import Address, SeerGame
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker


@pytest.mark.asyncio
@pytest.mark.parametrize("connect_fails", [False, True])
async def test_login_uses_connection_not_stale_maintenance_notice(  # noqa: C901 - complete two-stage socket login replay
    monkeypatch: pytest.MonkeyPatch, *, connect_fails: bool
) -> None:
    announcement_requests: list[str] = []
    client_factory = httpx.AsyncClient

    def announcement(request: httpx.Request) -> httpx.Response:
        announcement_requests.append(str(request.url))
        return httpx.Response(200, json=[{"type": 3, "content": "旧维护公告"}])

    monkeypatch.setattr(
        game_module.httpx,
        "AsyncClient",
        lambda: client_factory(transport=httpx.MockTransport(announcement)),
    )

    async def session(*_args: object) -> bytes:
        return b"test-session"

    async def address(_url: str) -> Address:
        return Address("example.invalid", 1234)

    async def no_sleep(_seconds: float) -> None:
        return

    class Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.event_listener: EventListener[Any, Any, Any] = EventListener()
            self.is_connected = False

        async def connect(self, _host: str, _port: int) -> None:
            if connect_fails:
                raise ConnectionError
            self.is_connected = True

        def disconnect(self) -> None:
            self.is_connected = False

        async def send_and_wait(
            self, command: object, *_args: object, **_kwargs: object
        ) -> Any:
            if command == COMMAND_ID.COMMEND_ONLINE:
                return None, SimpleNamespace(
                    svr_list=[
                        SimpleNamespace(
                            online_id=1,
                            ip=b"example.invalid",
                            port=1234,
                        )
                    ]
                )
            return None, b"ok"

    async def login_connection(*_args: object, **_kwargs: object) -> Connection:
        return Connection()

    monkeypatch.setattr(SeerGame, "_fetch_session_token", staticmethod(session))
    monkeypatch.setattr(SeerGame, "_fetch_login_server_addr", staticmethod(address))
    monkeypatch.setattr(game_module.SeerConnect, "new_client", login_connection)
    monkeypatch.setattr(game_module, "SeerEncryptConnect", Connection)
    monkeypatch.setattr(game_module.asyncio, "sleep", no_sleep)
    game = SeerGame(
        123456,
        "test-only",
        login_server_url="https://example.invalid",
        operations=HeadlessOperationTracker(),
        spawn=TaskOwner().create,
    )
    if connect_fails:
        with pytest.raises(ConnectionError):
            await game.login()
        assert not game.is_logged_in
    else:
        await game.login()
        assert game.is_logged_in
        game.logout()
    assert announcement_requests == []
