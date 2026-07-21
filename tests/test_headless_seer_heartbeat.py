import asyncio
from asyncio import StreamWriter
from typing import Any, cast

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.headless_seer.core.connect import AbstractSocketConnect
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.headless_seer.type_hint import CommandID
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class FakeConnect(AbstractSocketConnect[CommandID[Any], object]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sent_commands: list[CommandID[Any]] = []

    async def send(
        self,
        command_id: CommandID[Any],
        *_body: Any,
    ) -> CommandID[Any]:
        self.sent_commands.append(command_id)
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
            spawn=TaskOwner().create,
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
            operations=HeadlessOperationTracker(),
            spawn=TaskOwner().create,
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


def test_socket_requests_wait_for_the_previous_response() -> None:
    async def run() -> None:
        client = FakeConnect(
            asyncio.get_running_loop(),
            spawn=TaskOwner().create,
        )
        first_command_id = CommandID[Any](2051)
        second_command_id = CommandID[Any](2052)

        first = asyncio.create_task(
            client.send_and_wait(first_command_id, timeout=1)
        )
        await asyncio.sleep(0)
        second = asyncio.create_task(
            client.send_and_wait(second_command_id, timeout=1)
        )
        await asyncio.sleep(0)

        assert client.sent_commands == [first_command_id]

        first_response = object()
        assert client._resolve_pending(first_command_id, first_response)
        assert await first == (first_response,)

        expected_send_count = 2
        for _ in range(10):
            if len(client.sent_commands) == expected_send_count:
                break
            await asyncio.sleep(0)
        assert client.sent_commands == [first_command_id, second_command_id]

        second_response = object()
        assert client._resolve_pending(second_command_id, second_response)
        assert await second == (second_response,)

    asyncio.run(run())


def test_request_timeout_resets_connection_and_discards_pending_request() -> None:
    async def run() -> None:
        disconnect_called = asyncio.Event()

        async def on_disconnect() -> None:
            disconnect_called.set()

        client = FakeConnect(
            asyncio.get_running_loop(),
            spawn=TaskOwner().create,
            on_disconnect=on_disconnect,
        )
        writer = FakeWriter()
        client._writer = cast("StreamWriter", writer)
        command_id = CommandID[Any](2051)

        with pytest.raises(asyncio.TimeoutError):
            await client.send_and_wait(command_id, timeout=0)

        await asyncio.wait_for(disconnect_called.wait(), timeout=1)

        assert writer.closed
        assert client._writer is None
        assert not client._pending_requests

    asyncio.run(run())
