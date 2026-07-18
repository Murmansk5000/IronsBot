import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

import nonebot
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.message import (
    GroupScheduledMessageAction,
    PrivateScheduledMessageAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE
from ironsbot.plugins.messaging import matcher_rules, push_management_runtime, runtime
from ironsbot.plugins.messaging import schedules as message_schedules
from ironsbot.shared.messaging.push_subscription_models import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)
from tests.helpers.onebot_events import GroupMemberRole, group_member_message_event

SUPERUSER_ID = 1002
OVERRIDE_HOUR = 22
OVERRIDE_MINUTE = 30
@dataclass(frozen=True, slots=True)
class FakeMessageConfig:
    push_unsubscribe: PushUnsubscribeConfig
    private_schedules: list[PrivateScheduledMessageAction] = field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FakeJob:
    id: str


def _private_schedule(
    message: str,
    *,
    schedule_id: str = "private",
    hour: int = 23,
    minute: int = 0,
) -> PrivateScheduledMessageAction:
    return PrivateScheduledMessageAction(
        id=schedule_id,
        message=message,
        hour=hour,
        minute=minute,
    )


def _group_schedule(
    message: str,
    *,
    at_user_ids: list[int] | None = None,
    schedule_id: str = "group",
    hour: int = 23,
    minute: int = 0,
) -> GroupScheduledMessageAction:
    return GroupScheduledMessageAction(
        id=schedule_id,
        message=message,
        at_user_ids=at_user_ids or [],
        hour=hour,
        minute=minute,
    )


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        job_id = kwargs.get("id")
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def get_jobs(self) -> list[FakeJob]:
        return [FakeJob(id=str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]


def _group_event(
    text: str = "TD",
    *,
    user_id: int = SUPERUSER_ID,
    role: GroupMemberRole = "member",
):
    return group_member_message_event(
        text,
        user_id=user_id,
        group_id=2002,
        role=role,
    )


def test_messaging_startup_prunes_preferences_before_registering_jobs(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_prune() -> PushPreferencePruneResult:
        calls.append("prune")
        return PushPreferencePruneResult(
            unsubscriptions_deleted=2,
            time_preferences_deleted=1,
        )

    async def fake_register(_scheduler: object) -> None:
        calls.append("register")

    monkeypatch.setattr(runtime, "prune_stale_push_preferences", fake_prune)
    monkeypatch.setattr(runtime, "register_message_schedules", fake_register)

    asyncio.run(runtime.start_messaging(object()))

    assert calls == ["prune", "register"]


def test_messaging_startup_continues_when_preference_cleanup_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_prune() -> PushPreferencePruneResult:
        calls.append("prune")
        raise RuntimeError

    async def fake_register(_scheduler: object) -> None:
        calls.append("register")

    monkeypatch.setattr(runtime, "prune_stale_push_preferences", fake_prune)
    monkeypatch.setattr(runtime, "register_message_schedules", fake_register)

    asyncio.run(runtime.start_messaging(object()))

    assert calls == ["prune", "register"]


def test_push_subscription_menu_prompt_marks_current_state() -> None:
    prompt = push_management_runtime._push_subscription_menu_prompt(
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
    prompt = push_management_runtime._push_subscription_menu_prompt(
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
        matcher_rules,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(
        matcher_rules.match_push_subscription_command(_group_event(), {})
    )


def test_group_push_subscription_command_allows_regular_member_to_view(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matcher_rules,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(
        matcher_rules.match_push_subscription_command(_group_event(), {})
    )


def test_group_push_subscription_management_command_matches_regular_member(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        matcher_rules,
        "get_message_config",
        lambda: FakeMessageConfig(push_unsubscribe=PushUnsubscribeConfig()),
    )

    assert asyncio.run(
        matcher_rules.match_push_subscription_command(
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

    monkeypatch.setattr(
        message_schedules,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )
    monkeypatch.setattr(
        message_schedules,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(
                data_path=str(tmp_path / "unsubscribe.sqlite")
            )
        ),
    )
    monkeypatch.setattr(message_schedules, "users_for_feature", lambda _feature: [2001])
    monkeypatch.setattr(message_schedules, "users_with_superusers", list)
    monkeypatch.setattr(
        message_schedules,
        "groups_for_feature",
        lambda _feature: [1001],
    )
    monkeypatch.setattr(
        message_schedules,
        "append_fire_manual_ad_for_group",
        lambda message, _group_id: f"{message}\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    )

    asyncio.run(
        message_schedules.send_private_schedule(
            _private_schedule("私聊定时")
        )
    )
    asyncio.run(
        message_schedules.send_group_schedule(
            _group_schedule("群定时", at_user_ids=[3001])
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

    monkeypatch.setattr(
        message_schedules,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )
    monkeypatch.setattr(
        message_schedules,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
    )
    monkeypatch.setattr(
        message_schedules,
        "users_for_feature",
        lambda _feature: [2001, 2002],
    )
    monkeypatch.setattr(message_schedules, "users_with_superusers", list)

    asyncio.run(
        message_schedules.send_private_schedule(
            _private_schedule("私聊定时")
        )
    )

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

    monkeypatch.setattr(
        message_schedules,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )
    monkeypatch.setattr(
        message_schedules,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
    )
    monkeypatch.setattr(
        message_schedules,
        "groups_for_feature",
        lambda _feature: [1001, 1002],
    )

    asyncio.run(
        message_schedules.send_group_schedule(
            _group_schedule("group push", at_user_ids=[], schedule_id="daily")
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
    task = GroupScheduledMessageAction(
        message="group push",
        at_user_ids=[],
        id="daily",
        hour=23,
        minute=0,
    )
    scheduler = FakeScheduler()

    monkeypatch.setattr(
        message_schedules,
        "get_message_config",
        lambda: FakeMessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path)),
            group_schedules=[task],
        ),
    )
    monkeypatch.setattr(
        message_schedules,
        "groups_for_feature",
        lambda _feature: [1001, 1002],
    )

    asyncio.run(message_schedules.register_message_schedules(scheduler))

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
