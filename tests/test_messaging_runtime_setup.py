import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.fire_manual_ad.service import FIRE_MANUAL_LINK_MESSAGE
from ironsbot.plugins.messaging import runtime


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


@dataclass(frozen=True, slots=True)
class FakePrivateSchedule:
    message: str
    feature: str = "text_push"
    id: str = "private"


@dataclass(frozen=True, slots=True)
class FakeGroupSchedule:
    message: str
    at_user_ids: list[int]
    feature: str = "text_push"
    id: str = "group"


def test_messaging_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        runtime._messaging_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    runtime._setup_messaging_runtime(driver, scheduler)
    runtime._setup_messaging_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_scheduled_messages_append_fire_manual_ad(
    monkeypatch: MonkeyPatch,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(runtime, "users_for_feature", lambda _feature: [2001])
    monkeypatch.setattr(runtime, "users_with_superusers", list)
    monkeypatch.setattr(runtime, "groups_for_feature", lambda _feature: [1001])

    asyncio.run(runtime._send_private_schedule(FakePrivateSchedule(message="私聊定时")))
    asyncio.run(
        runtime._send_group_schedule(
            FakeGroupSchedule(message="群定时", at_user_ids=[3001])
        )
    )

    assert [message for message, _kwargs in sent] == [
        f"私聊定时\n\n{FIRE_MANUAL_LINK_MESSAGE}",
        f"群定时\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    ]
    assert sent[0][1]["private_user_ids"] == [2001]
    assert sent[1][1]["group_ids"] == [1001]
    assert sent[1][1]["group_at_user_ids"] == [3001]
