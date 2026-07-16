import asyncio
from typing import ClassVar

from pytest import MonkeyPatch

from ironsbot.integrations.headless_seer import client as client_module
from ironsbot.integrations.headless_seer.client import ClientManager

EXPECTED_REPLACEMENT_COUNT = 2


class _FakeSeerGame:
    instances: ClassVar[list["_FakeSeerGame"]] = []
    login_started: ClassVar[asyncio.Event]
    login_release: ClassVar[asyncio.Event]

    def __init__(self, user_id: int, _password: str, **_kwargs: object) -> None:
        self.user_id = user_id
        self.is_logged_in = False
        self.logout_calls = 0
        self.schedule_reconnect_calls = 0
        self.instances.append(self)

    async def login(self) -> None:
        self.login_started.set()
        await self.login_release.wait()
        self.is_logged_in = True

    def logout(self) -> None:
        self.logout_calls += 1
        self.is_logged_in = False

    def schedule_reconnect(self) -> None:
        self.schedule_reconnect_calls += 1


def _reset_fake_game() -> None:
    _FakeSeerGame.instances = []
    _FakeSeerGame.login_started = asyncio.Event()
    _FakeSeerGame.login_release = asyncio.Event()


def test_client_manager_serializes_and_reuses_concurrent_login(
    monkeypatch: MonkeyPatch,
) -> None:
    async def run() -> None:
        _reset_fake_game()
        monkeypatch.setattr(client_module, "SeerGame", _FakeSeerGame)
        manager = ClientManager()

        first_task = asyncio.create_task(
            manager.login(123456, "password", "https://example.invalid")
        )
        await _FakeSeerGame.login_started.wait()
        second_task = asyncio.create_task(
            manager.login(123456, "password", "https://example.invalid")
        )
        await asyncio.sleep(0)

        assert len(_FakeSeerGame.instances) == 1
        _FakeSeerGame.login_release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert first is second
        assert len(_FakeSeerGame.instances) == 1

    asyncio.run(run())


def test_client_manager_stops_disconnected_client_before_replacement(
    monkeypatch: MonkeyPatch,
) -> None:
    async def run() -> None:
        _reset_fake_game()
        monkeypatch.setattr(client_module, "SeerGame", _FakeSeerGame)
        manager = ClientManager()
        _FakeSeerGame.login_release.set()

        first = await manager.login(
            123456,
            "password",
            "https://example.invalid",
        )
        first_fake = _FakeSeerGame.instances[0]
        first_fake.is_logged_in = False
        second = await manager.login(
            123456,
            "password",
            "https://example.invalid",
        )

        assert first is not second
        assert first_fake.logout_calls == 1
        assert len(_FakeSeerGame.instances) == EXPECTED_REPLACEMENT_COUNT

    asyncio.run(run())
