import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import HeadlessNoticeConfig
from ironsbot.plugins.headless_seer_notice import (
    runtime as headless_notice_runtime,
)
from ironsbot.services.headless_seer_notice import service as headless_notice_service
from ironsbot.services.headless_seer_notice import state as headless_notice_state

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_headless_notice_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    registered_checks: list[tuple[str, object]] = []
    monkeypatch.setitem(
        headless_notice_runtime._headless_notice_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setattr(
        headless_notice_runtime,
        "register_startup_check",
        lambda name, check: registered_checks.append((name, check)),
    )
    driver = FakeDriver()
    scheduler = object()

    headless_notice_runtime._setup_headless_notice_runtime(driver, scheduler)
    headless_notice_runtime._setup_headless_notice_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert registered_checks == [
        ("headless_seer_login", headless_notice_runtime._startup_check)
    ]


def test_register_reconnect_checks_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        headless_notice_runtime,
        "get_headless_notice_config",
        lambda: HeadlessNoticeConfig(reconnect_check_times="00:01,00:02"),
    )

    headless_notice_runtime._register_reconnect_checks(scheduler)

    assert scheduler.jobs == [
        {
            "func": headless_notice_runtime._daily_reconnect_check,
            "trigger": "cron",
            "id": "headless_reconnect_check:00:01",
            "replace_existing": True,
            "args": ["00:01"],
            "hour": 0,
            "minute": 1,
            "second": 0,
            "timezone": "Asia/Shanghai",
        },
        {
            "func": headless_notice_runtime._daily_reconnect_check,
            "trigger": "cron",
            "id": "headless_reconnect_check:00:02",
            "replace_existing": True,
            "args": ["00:02"],
            "hour": 0,
            "minute": 2,
            "second": 0,
            "timezone": "Asia/Shanghai",
        },
    ]


def test_startup_check_sends_failure_through_admin_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object, object]] = []
    unavailable: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(
        headless_notice_runtime,
        "get_headless_notice_config",
        lambda: HeadlessNoticeConfig(login_notice=True),
    )
    monkeypatch.setattr(
        headless_notice_service,
        "headless_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        headless_notice_service,
        "headless_login_failure_reason",
        lambda: "登录失败",
    )
    monkeypatch.setattr(
        headless_notice_service,
        "headless_user_id_text",
        lambda: "123456",
    )

    async def fake_mark_unavailable(
        reason: str,
        *,
        source: str,
        notify: bool = True,
    ) -> None:
        unavailable.append((reason, source, notify))

    async def fake_send_admin_notice(message: object, **kwargs: object) -> object:
        sent_messages.append(
            (
                str(message),
                kwargs.get("subscription_key"),
                kwargs.get("action_name"),
            )
        )
        return object()

    monkeypatch.setattr(
        headless_notice_runtime,
        "mark_headless_unavailable",
        fake_mark_unavailable,
    )
    monkeypatch.setattr(
        headless_notice_runtime,
        "send_admin_notice",
        fake_send_admin_notice,
    )

    asyncio.run(headless_notice_runtime._startup_check(cast("Bot", object())))

    assert unavailable == [("登录失败", "启动检查", False)]
    assert sent_messages == [
        (
            "无头米米号登录未成功。\n"
            "米米号：123456\n"
            "状态：登录失败\n"
            "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。",
            "headless_seer_notice",
            "headless seer failure notice",
        )
    ]


def test_headless_state_notice_uses_admin_notice_delivery(
    monkeypatch: MonkeyPatch,
) -> None:
    sent_messages: list[tuple[str, object, object]] = []
    monkeypatch.setattr(
        headless_notice_state,
        "get_headless_notice_config",
        HeadlessNoticeConfig,
    )
    monkeypatch.setattr(
        headless_notice_service,
        "headless_user_id_text",
        lambda: "123456",
    )

    async def fake_send_admin_notice(message: object, **kwargs: object) -> object:
        sent_messages.append(
            (
                str(message),
                kwargs.get("subscription_key"),
                kwargs.get("action_name"),
            )
        )
        return object()

    monkeypatch.setattr(
        headless_notice_state,
        "send_admin_notice",
        fake_send_admin_notice,
    )

    asyncio.run(
        headless_notice_state._send_headless_state_notice(
            connected=False,
            reason="登录断开",
            source="测试",
            user_id=None,
        )
    )

    assert sent_messages == [
        (
            "无头米米号已掉线。\n米米号：123456\n状态：登录断开\n来源：测试",
            "headless_seer_notice",
            "headless state notice",
        )
    ]
