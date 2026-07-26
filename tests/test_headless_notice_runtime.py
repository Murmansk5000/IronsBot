import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pytest import MonkeyPatch

from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.plugins.operations.headless import register_reconnect_jobs
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.operations.headless import HeadlessService
from tests.helpers.runtime import build_test_runtime

USER_ID = 123456


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def build_service(
    *,
    notices: HeadlessNoticeConfig | None = None,
    now: object | None = None,
) -> HeadlessService:
    runtime = build_test_runtime()
    return HeadlessService(
        ClientManager(runtime.tasks.create),
        HeadlessConfig(user_id=USER_ID, password="md5"),
        notices or HeadlessNoticeConfig(),
        runtime.admin_notices,
        now=now,  # type: ignore[arg-type]
    )


def test_register_reconnect_checks_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    service = build_service(
        notices=HeadlessNoticeConfig(reconnect_check_times="00:01,00:02")
    )
    register_reconnect_jobs(scheduler, service)

    assert scheduler.jobs == [
        {
            "func": service.reconnect,
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
            "func": service.reconnect,
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
    sent: list[tuple[str, object, object]] = []
    service = build_service(
        notices=HeadlessNoticeConfig(
            login_notice=True,
            login_notice_message="login {user_id} {reason}",
        )
    )

    async def fake_send(
        _service: AdminNoticeService,
        message: object,
        **kwargs: object,
    ) -> object:
        sent.append(
            (
                str(message),
                kwargs.get("subscription_key"),
                kwargs.get("action_name"),
            )
        )
        return object()

    monkeypatch.setattr(AdminNoticeService, "send", fake_send)

    asyncio.run(service.check_on_connect())

    assert sent == [
        (
            "login 123456 Headless Seer client is not logged in",
            "headless_seer_notice",
            "headless seer failure notice",
        )
    ]


def test_headless_state_notice_uses_admin_notice_delivery(
    monkeypatch: MonkeyPatch,
) -> None:
    sent: list[tuple[str, object, object]] = []
    service = build_service(
        notices=HeadlessNoticeConfig(
            state_offline_message="offline {user_id} {reason} {source}",
        ),
        now=lambda: datetime(
            2026,
            7,
            21,
            12,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
    )

    async def fake_send(
        _service: AdminNoticeService,
        message: object,
        **kwargs: object,
    ) -> object:
        sent.append(
            (
                str(message),
                kwargs.get("subscription_key"),
                kwargs.get("action_name"),
            )
        )
        return object()

    monkeypatch.setattr(AdminNoticeService, "send", fake_send)

    asyncio.run(service.mark_available(source="initial", notify=False))
    asyncio.run(service.mark_unavailable("disconnected", source="test"))

    assert sent == [
        (
            "offline 123456 disconnected test",
            "headless_seer_notice",
            "headless state notice",
        )
    ]


def test_headless_recovery_notice_includes_offline_duration(
    monkeypatch: MonkeyPatch,
) -> None:
    sent: list[str] = []
    offline_at = datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    timestamps = iter(
        [
            offline_at - timedelta(seconds=1),
            offline_at,
            offline_at + timedelta(hours=1, minutes=2, seconds=3),
        ]
    )
    service = build_service(
        notices=HeadlessNoticeConfig(
            state_offline_message="offline {user_id} {reason} {source}",
            state_online_message="online {user_id} {offline_duration} {source}",
        ),
        now=lambda: next(timestamps),
    )

    async def fake_send(
        _service: AdminNoticeService,
        message: object,
        **_kwargs: object,
    ) -> object:
        sent.append(str(message))
        return object()

    monkeypatch.setattr(AdminNoticeService, "send", fake_send)

    asyncio.run(service.mark_available(source="initial", notify=False))
    asyncio.run(service.mark_unavailable("disconnected", source="offline"))
    asyncio.run(service.mark_available(source="reconnect", user_id=USER_ID))

    assert sent == [
        "offline 123456 disconnected offline",
        "online 123456 1小时2分钟 reconnect",
    ]
