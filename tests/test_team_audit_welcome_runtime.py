from __future__ import annotations

from typing import TYPE_CHECKING, get_type_hints

from nonebot.adapters.onebot.v11 import Bot

from ironsbot.plugins.team_audit_welcome import runtime

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch


class FakeDriver:
    def __init__(self) -> None:
        self.bot_connect_handlers: list[Callable[[object], object]] = []

    def on_bot_connect(
        self,
        handler: Callable[[object], object],
    ) -> Callable[[object], object]:
        self.bot_connect_handlers.append(handler)
        return handler


def test_team_audit_runtime_bot_connect_annotation_is_resolvable(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        runtime._team_audit_welcome_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    runtime._setup_team_audit_welcome_runtime(driver, scheduler)
    runtime._setup_team_audit_welcome_runtime(driver, scheduler)

    assert len(driver.bot_connect_handlers) == 1
    assert get_type_hints(driver.bot_connect_handlers[0])["bot"] is Bot
