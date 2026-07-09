import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import StartupConfig
from ironsbot.plugins.startup_notice import runtime as startup_notice_runtime
from ironsbot.plugins.startup_notice.runtime import (
    _setup_startup_notice_runtime,
    _startup_notice_runtime_state,
    send_startup_notice,
)
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary
from ironsbot.shared.plugin_runtime import startup_ready, startup_ready_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


class FakeDriver:
    def __init__(self) -> None:
        self.bot_connect_handlers: list[Callable[[object], object]] = []

    def on_bot_connect(
        self,
        handler: Callable[[object], object],
    ) -> Callable[[object], object]:
        self.bot_connect_handlers.append(handler)
        return handler


def test_startup_ready_runtime_setup_registers_bot_connect_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        startup_ready_runtime._startup_ready_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()

    startup_ready_runtime._setup_startup_ready_runtime(driver)
    startup_ready_runtime._setup_startup_ready_runtime(driver)

    assert driver.bot_connect_handlers == [
        startup_ready.run_registered_startup_checks
    ]


def test_startup_notice_runtime_setup_registers_bot_connect_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        _startup_notice_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()

    _setup_startup_notice_runtime(driver)
    _setup_startup_notice_runtime(driver)

    assert driver.bot_connect_handlers == [send_startup_notice]


def test_startup_notice_appends_db_sync_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sent",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sending",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime,
        "get_startup_config",
        lambda: StartupConfig(enabled=True, message="机器人已开启。", delay=0),
    )

    async def fake_ensure_startup_ready(_bot: object) -> None:
        return None

    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        startup_notice_runtime,
        "ensure_startup_ready",
        fake_ensure_startup_ready,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "superuser_loader",
        lambda: {1},
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "feature_group_loader",
        lambda _feature: [],
    )
    monkeypatch.setattr(
        "ironsbot.plugins.server_status.runtime.get_startup_docker_update_notice",
        lambda: None,
    )
    monkeypatch.setattr(
        "ironsbot.plugins.db_sync.runtime.get_startup_sync_notice",
        lambda: "启动数据同步已是最新，无需更新：seerapi, aliases",
    )
    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(startup_notice_runtime.send_startup_notice(cast("Bot", object())))

    assert sent_messages == [
        ("机器人已开启。", "startup_notice"),
        (
            "启动数据同步已是最新，无需更新：seerapi, aliases",
            "startup_data_sync",
        ),
    ]


def test_startup_notice_appends_docker_update_before_db_sync(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object]] = []
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sent",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service.state,
        "sending",
        False,
    )
    monkeypatch.setattr(
        startup_notice_runtime,
        "get_startup_config",
        lambda: StartupConfig(enabled=True, message="机器人已开启。", delay=0),
    )

    async def fake_ensure_startup_ready(_bot: object) -> None:
        return None

    async def fake_send_broadcast_message(
        message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent_messages.append((str(message), kwargs.get("subscription_key")))
        return TargetSendSummary([MessageTarget("private", 1)], [])

    monkeypatch.setattr(
        startup_notice_runtime,
        "ensure_startup_ready",
        fake_ensure_startup_ready,
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "superuser_loader",
        lambda: {1},
    )
    monkeypatch.setattr(
        startup_notice_runtime.startup_notice_service,
        "feature_group_loader",
        lambda _feature: [],
    )
    monkeypatch.setattr(
        "ironsbot.plugins.server_status.runtime.get_startup_docker_update_notice",
        lambda: "Docker 自更新任务已启动：ironsbot",
    )
    monkeypatch.setattr(
        "ironsbot.plugins.db_sync.runtime.get_startup_sync_notice",
        lambda: "启动数据同步已是最新，无需更新：seerapi",
    )
    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    asyncio.run(startup_notice_runtime.send_startup_notice(cast("Bot", object())))

    assert sent_messages == [
        ("机器人已开启。", "startup_notice"),
        (
            "Docker 自更新任务已启动：ironsbot",
            "startup_docker_update",
        ),
        ("启动数据同步已是最新，无需更新：seerapi", "startup_data_sync"),
    ]
