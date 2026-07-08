import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.plugins.messaging import runtime
from ironsbot.shared.messaging.push_subscriptions import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
    PushUnsubscribeStore,
)
from ironsbot.shared.promotions import FIRE_MANUAL_LINK_MESSAGE

SUPERUSER_ID = 1002
OVERRIDE_HOUR = 22
OVERRIDE_MINUTE = 30


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
    name: str = ""
    enabled: bool = True
    hour: int = 23
    minute: int = 0
    day_of_week: str | None = None


@dataclass(frozen=True, slots=True)
class FakeGroupSchedule:
    message: str
    at_user_ids: list[int]
    feature: str = "text_push"
    id: str = "group"
    name: str = ""
    enabled: bool = True
    hour: int = 23
    minute: int = 0
    day_of_week: str | None = None


@dataclass(frozen=True, slots=True)
class FakeMessageConfig:
    push_unsubscribe: PushUnsubscribeConfig
    private_schedules: list[FakePrivateSchedule] = field(default_factory=list)
    group_schedules: list[FakeGroupSchedule] = field(default_factory=list)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        job_id = kwargs.get("id")
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def get_jobs(self) -> list[object]:
        return [
            type("FakeJob", (), {"id": str(job["id"])})()
            for job in self.jobs
        ]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]


def _group_event(
    text: str = "TD",
    *,
    user_id: int = SUPERUSER_ID,
    role: str = "member",
) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=2002,
        sender={"role": role},
    )


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


def test_push_subscription_menu_prompt_marks_current_state() -> None:
    prompt = runtime._push_subscription_menu_prompt(
        "private",
        [
            PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
            PushSubscriptionOption(
                "startup_data_sync",
                "启动数据同步通知",
                "admin_notice",
                unsubscribed=True,
            ),
        ],
    )

    assert "请选择要切换的私聊推送订阅：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "2. ❌ 启动数据同步通知" in prompt
    assert "输入序号切换" in prompt


def test_push_subscription_menu_prompt_can_be_read_only() -> None:
    prompt = runtime._push_subscription_menu_prompt(
        "group",
        [
            PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
        ],
        read_only=True,
    )

    assert "本群推送订阅状态" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "普通群员仅可查看" in prompt
    assert "输入序号切换" not in prompt


def test_group_push_subscription_command_allows_superuser_member(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "is_superuser",
        lambda user_id: user_id == SUPERUSER_ID,
    )
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(runtime._match_push_subscription_command(_group_event(), {}))


def test_group_push_subscription_command_allows_regular_member_to_view(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(
        runtime._match_push_subscription_command(_group_event(), {})
    )


def test_group_push_subscription_management_command_matches_regular_member(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(
        runtime._match_push_subscription_command(
            _group_event("推送管理", user_id=3003),
            {},
        )
    )


def test_scheduled_messages_append_fire_manual_ad(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        limiter = kwargs.get("message_limiter")
        group_ids = kwargs.get("group_ids")
        if limiter is not None and isinstance(group_ids, list) and group_ids:
            message = limiter(message, group_ids[0])  # type: ignore[operator]
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(
                data_path=str(tmp_path / "unsubscribe.sqlite")
            )
        ),
    )
    monkeypatch.setattr(runtime, "users_for_feature", lambda _feature: [2001])
    monkeypatch.setattr(runtime, "users_with_superusers", list)
    monkeypatch.setattr(runtime, "groups_for_feature", lambda _feature: [1001])
    monkeypatch.setattr(
        runtime,
        "append_fire_manual_ad_for_group",
        lambda message, _group_id: f"{message}\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    )

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
    assert sent[0][1]["subscription_key"] == "private"
    assert sent[1][1]["group_ids"] == [1001]
    assert sent[1][1]["group_at_user_ids"] == [3001]
    assert sent[1][1]["subscription_key"] == "group"


def test_private_schedule_passes_subscription_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    data_path = tmp_path / "unsubscribe.sqlite"

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
    )
    monkeypatch.setattr(runtime, "users_for_feature", lambda _feature: [2001, 2002])
    monkeypatch.setattr(runtime, "users_with_superusers", list)

    asyncio.run(runtime._send_private_schedule(FakePrivateSchedule(message="私聊定时")))

    assert sent[0][1]["private_user_ids"] == [2001, 2002]
    assert sent[0][1]["subscription_key"] == "private"


def test_group_schedule_skips_default_time_for_overridden_group(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    data_path = tmp_path / "unsubscribe.sqlite"
    store = PushUnsubscribeStore(data_path)
    store.set_time_preference(
        "group",
        1001,
        "daily",
        CRON_TIME_PREFERENCE,
        f"{OVERRIDE_HOUR:02d}:{OVERRIDE_MINUTE:02d}",
    )

    async def fake_send_broadcast_message(
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(runtime, "send_broadcast_message", fake_send_broadcast_message)
    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
    )
    monkeypatch.setattr(runtime, "groups_for_feature", lambda _feature: [1001, 1002])

    asyncio.run(
        runtime._send_group_schedule(
            FakeGroupSchedule(message="group push", at_user_ids=[], id="daily")
        )
    )

    assert sent[0][1]["group_ids"] == [1002]
    assert sent[0][1]["subscription_key"] == "daily"


def test_group_schedule_override_job_targets_only_overridden_group(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "unsubscribe.sqlite"
    store = PushUnsubscribeStore(data_path)
    store.set_time_preference(
        "group",
        1001,
        "daily",
        CRON_TIME_PREFERENCE,
        f"{OVERRIDE_HOUR:02d}:{OVERRIDE_MINUTE:02d}",
    )
    task = FakeGroupSchedule(
        message="group push",
        at_user_ids=[],
        id="daily",
        hour=23,
        minute=0,
    )
    scheduler = FakeScheduler()

    monkeypatch.setattr(
        runtime,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path)),
            group_schedules=[task],
        ),
    )
    monkeypatch.setattr(runtime, "groups_for_feature", lambda _feature: [1001, 1002])

    asyncio.run(runtime.register_message_schedules(scheduler))

    assert [job["id"] for job in scheduler.jobs] == [
        "message_action_group_schedule_daily",
        "message_action_group_schedule_daily_override_1001",
    ]
    override_job = scheduler.jobs[1]
    assert override_job["hour"] == OVERRIDE_HOUR
    assert override_job["minute"] == OVERRIDE_MINUTE
    assert override_job["kwargs"] == {
        "task": task,
        "index": 1,
        "target_group_ids": (1001,),
    }
