import asyncio
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.composition import refresh_push_time_jobs
from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import (
    GroupScheduledMessageAction,
    MessageConfig,
    PrivateScheduledMessageAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE
from ironsbot.plugins.messaging import matcher_rules, runtime
from ironsbot.plugins.messaging import schedules as message_schedules
from ironsbot.plugins.messaging.push_subscription import (
    build_messaging_push_subscription_menu_prompt,
)
from ironsbot.plugins.messaging.push_time import PushTimeOption
from ironsbot.plugins.messaging.runtime_service import MessagingResources
from ironsbot.shared.messaging.push_subscription_models import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)
from tests.helpers.onebot_events import GroupMemberRole, group_member_message_event
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.services.activity.service import ActivityService

SUPERUSER_ID = 1002
OVERRIDE_HOUR = 22
OVERRIDE_MINUTE = 30


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


def _messaging_resources(
    data_path: Path,
    *,
    group_schedules: list[GroupScheduledMessageAction] | None = None,
    group_policy: dict[str, list[str]] | None = None,
    user_policy: dict[str, list[str]] | None = None,
    superusers: tuple[int, ...] = (),
) -> MessagingResources:
    config = MessageConfig(
        push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path)),
        group_schedules=group_schedules or [],
    )
    resources = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy=group_policy or {},
            user_policy=user_policy or {},
        ),
        superuser_ids=superusers,
    )
    return MessagingResources(
        config,
        ActivityConfig(),
        PushUnsubscribeStore(data_path),
        resources.features,
        resources.priority,
        resources.delivery,
        lambda _target_type, _target_id: [],
    )


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

    def fake_prune(_messaging: MessagingResources) -> PushPreferencePruneResult:
        calls.append("prune")
        return PushPreferencePruneResult(
            unsubscriptions_deleted=2,
            time_preferences_deleted=1,
        )

    async def fake_register(
        _scheduler: object,
        _messaging: MessagingResources,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(runtime, "prune_stale_push_preferences", fake_prune)
    monkeypatch.setattr(message_schedules, "register_message_schedules", fake_register)

    asyncio.run(
        runtime.start_messaging(
            object(),
            _messaging_resources(Path("unused.sqlite")),
        )
    )

    assert calls == ["prune", "register"]


def test_messaging_startup_continues_when_preference_cleanup_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_prune(_messaging: MessagingResources) -> PushPreferencePruneResult:
        calls.append("prune")
        raise RuntimeError

    async def fake_register(
        _scheduler: object,
        _messaging: MessagingResources,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(runtime, "prune_stale_push_preferences", fake_prune)
    monkeypatch.setattr(message_schedules, "register_message_schedules", fake_register)

    asyncio.run(
        runtime.start_messaging(
            object(),
            _messaging_resources(Path("unused.sqlite")),
        )
    )

    assert calls == ["prune", "register"]


def test_push_time_refresh_uses_explicit_job_owner(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_register(
        scheduler: object,
        _messaging: MessagingResources,
    ) -> None:
        calls.append(("message", scheduler))

    class FakeActivityService:
        async def schedule_reminders(self, scheduler: object) -> None:
            calls.append(("activity", scheduler))

    scheduler = object()
    activity_service = cast("ActivityService", FakeActivityService())
    messaging = _messaging_resources(Path("unused.sqlite"))
    monkeypatch.setattr(message_schedules, "register_message_schedules", fake_register)
    option = PushTimeOption("test", "测试", "test", CRON_TIME_PREFERENCE, "", "")
    for preference_type in (
        CRON_TIME_PREFERENCE,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
    ):
        asyncio.run(
            refresh_push_time_jobs(
                replace(option, preference_type=preference_type),
                scheduler=scheduler,
                activity_service=activity_service,
                messaging=messaging,
            )
        )

    assert calls == [("message", scheduler), ("activity", scheduler)]


def test_push_subscription_menu_prompt_marks_current_state() -> None:
    prompt = build_messaging_push_subscription_menu_prompt(
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
    prompt = build_messaging_push_subscription_menu_prompt(
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


def test_group_push_subscription_command_allows_superuser_member() -> None:
    assert asyncio.run(
        matcher_rules.match_push_subscription_command(
            _group_event(),
            {},
            config=PushUnsubscribeConfig(),
        )
    )


def test_group_push_subscription_command_allows_regular_member_to_view() -> None:
    assert asyncio.run(
        matcher_rules.match_push_subscription_command(
            _group_event(),
            {},
            config=PushUnsubscribeConfig(),
        )
    )


def test_group_push_subscription_management_command_matches_regular_member() -> None:
    assert asyncio.run(
        matcher_rules.match_push_subscription_command(
            _group_event("推送管理", user_id=3003),
            {},
            config=PushUnsubscribeConfig(),
        )
    )


def test_scheduled_messages_append_fire_manual_ad(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push", "fire_manual_ad"]},
    )

    async def fake_send_broadcast_message(
        _delivery: object,
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
    asyncio.run(
        message_schedules.send_private_schedule(
            _private_schedule("私聊定时"),
            messaging=messaging,
        )
    )
    asyncio.run(
        message_schedules.send_group_schedule(
            _group_schedule("群定时", at_user_ids=[3001]),
            messaging=messaging,
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
    messaging = _messaging_resources(
        data_path,
        user_policy={
            "2001": ["text_push"],
            "2002": ["text_push"],
        },
    )

    async def fake_send_broadcast_message(
        _delivery: object,
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(
        message_schedules,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )
    asyncio.run(
        message_schedules.send_private_schedule(
            _private_schedule("私聊定时"),
            messaging=messaging,
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
    messaging = _messaging_resources(
        data_path,
        group_policy={
            "1001": ["text_push"],
            "1002": ["text_push"],
        },
    )
    messaging.store.set_time_preference(
        "group",
        1001,
        "daily",
        CRON_TIME_PREFERENCE,
        f"{OVERRIDE_HOUR:02d}:{OVERRIDE_MINUTE:02d}",
    )

    async def fake_send_broadcast_message(
        _delivery: object,
        message: str,
        **kwargs: object,
    ) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr(
        message_schedules,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )
    asyncio.run(
        message_schedules.send_group_schedule(
            _group_schedule("group push", at_user_ids=[], schedule_id="daily"),
            messaging=messaging,
        )
    )

    assert sent[0][1]["group_ids"] == [1002]
    assert sent[0][1]["subscription_key"] == "daily"


def test_group_schedule_override_job_targets_only_overridden_group(
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

    asyncio.run(
        message_schedules.register_message_schedules(
            scheduler,
            _messaging_resources(
                data_path,
                group_schedules=[task],
                group_policy={
                    "1001": ["text_push"],
                    "1002": ["text_push"],
                },
            ),
        )
    )

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
