import asyncio
from asyncio import StreamWriter
from typing import Any, cast

from ironsbot.integrations.headless_seer.core.connect import AbstractSocketConnect
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.headless_seer.type_hint import CommandID


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class FakeConnect(AbstractSocketConnect[CommandID[Any], object]):
    async def send(
        self,
        command_id: CommandID[Any],
        *_body: Any,
    ) -> CommandID[Any]:
        return command_id

    async def recv_bytes(self) -> bytes:
        return b""

    async def recv_packet(self) -> tuple[object] | None:
        return None


def test_heartbeat_timeout_marks_connection_lost() -> None:
    async def run() -> None:
        disconnect_called = asyncio.Event()

        async def on_heartbeat() -> None:
            raise TimeoutError

        async def on_disconnect() -> None:
            disconnect_called.set()

        client = FakeConnect(
            asyncio.get_running_loop(),
            heartbeat_interval=0,
            on_heartbeat=on_heartbeat,
            on_disconnect=on_disconnect,
        )
        writer = FakeWriter()
        client._writer = cast("StreamWriter", writer)

        await client._heartbeat_loop()
        await asyncio.wait_for(disconnect_called.wait(), timeout=1)

        assert writer.closed
        assert client._writer is None

    asyncio.run(run())


def test_seer_game_heartbeat_uses_self_user_info() -> None:
    async def run() -> None:
        seen_user_ids: list[int] = []

        game = SeerGame(
            123456,
            "password",
            login_server_url="https://example.invalid/unity-ip.txt",
        )

        async def get_user_info(user_id: int) -> object:
            seen_user_ids.append(user_id)
            return object()

        async def get_team_info(_team_id: int) -> object:
            raise AssertionError

        game.get_user_info = get_user_info  # type: ignore[method-assign]
        game.get_team_info = get_team_info  # type: ignore[method-assign]

        await game._send_heartbeat()

        assert seen_user_ids == [123456]

    asyncio.run(run())
