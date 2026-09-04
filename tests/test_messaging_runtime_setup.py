from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageConfig,
    MessageKeywordReplyAction,
    MessageMentionReplyAction,
    MessageScheduledAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE, MessageTarget
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.storage.push_subscriptions import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)
from ironsbot.plugins.messaging import matcher_rules
from ironsbot.services.messaging import schedules as message_schedules
from ironsbot.services.messaging.push_time import PushTimeOption
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from tests.helpers.onebot_events import (
    GroupMemberRole,
    group_member_message_event,
    private_message_event,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from pytest import MonkeyPatch

    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.messaging.subscriptions import PushTargetType

SUPERUSER_ID = 1002
OVERRIDE_HOUR = 22
OVERRIDE_MINUTE = 30


@dataclass(slots=True)
class FakeJob:
    id: str


def _schedule(
    message: str,
    *,
    at_user_ids: Sequence[str | int] | None = None,
    schedule_id: str = "daily",
    time: str = "23:00",
) -> MessageScheduledAction:
    return MessageScheduledAction(
        id=schedule_id,
        message=message,
        at_user_ids=list(at_user_ids or []),
        time=time,
    )


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> FakeJob:
        job_id = kwargs.get("id")
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob(id=str(job_id))

    def get_jobs(self) -> Sequence[FakeJob]:
        return [FakeJob(id=str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]


def _messaging_resources(  # noqa: PLR0913 - focused test fixture factory
    data_path: Path,
    *,
    commands: list[MessageCommandAction] | None = None,
    keyword_replies: list[MessageKeywordReplyAction] | None = None,
    mention_replies: list[MessageMentionReplyAction] | None = None,
    schedules: list[MessageScheduledAction] | None = None,
    group_policy: dict[str, list[str]] | None = None,
    user_policy: dict[str, list[str]] | None = None,
    superusers: tuple[int, ...] = (),
    store: PushUnsubscribeStore | None = None,
    extra_push_options: (
        Callable[[PushTargetType, int], list[PushSubscriptionOption]] | None
    ) = None,
    prepare_extra_push_options: (
        Callable[[PushTargetType, int], Awaitable[str | None]] | None
    ) = None,
) -> MessagingService:
    config = MessageConfig(
        push_unsubscribe=PushUnsubscribeConfig(),
        commands=commands or [],
        keyword_replies=keyword_replies or [],
        mention_replies=mention_replies or [],
        schedules=schedules or [],
    )
    resources = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy=group_policy or {},
            user_policy=user_policy or {},
        ),
        superuser_ids=superusers,
        command_features=config.command_feature_keys,
        state_path=data_path,
    )
    return MessagingService(
        config,
        ActivityConfig(),
        store or PushUnsubscribeStore(data_path),
        resources.features,
        resources.delivery,
        (extra_push_options or (lambda _target_type, _target_id: []),),
        _push_message_limiter=partial(
            append_fire_manual_ad_for_target,
            resources.features,
        ),
        _prepare_extra_push_options=prepare_extra_push_options,
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
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_prune(_messaging: MessagingService) -> PushPreferencePruneResult:
        calls.append("prune")
        return PushPreferencePruneResult(
            unsubscriptions_deleted=2,
            time_preferences_deleted=1,
        )

    async def fake_register(
        _messaging: MessagingService,
        _scheduler: object,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(MessagingService, "_prune_stale_preferences", fake_prune)
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)

    asyncio.run(
        _messaging_resources(tmp_path / "unsubscribe.sqlite").start(
            FakeScheduler(),
        )
    )

    assert calls == ["prune", "register"]


def test_messaging_startup_continues_when_preference_cleanup_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_prune(_messaging: MessagingService) -> PushPreferencePruneResult:
        calls.append("prune")
        raise RuntimeError

    async def fake_register(
        _messaging: MessagingService,
        _scheduler: object,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(MessagingService, "_prune_stale_preferences", fake_prune)
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)

    asyncio.run(
        _messaging_resources(tmp_path / "unsubscribe.sqlite").start(
            FakeScheduler(),
        )
    )

    assert calls == ["prune", "register"]


def test_push_time_refresh_uses_explicit_job_owner(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_register(
        _messaging: MessagingService,
        scheduler: object,
    ) -> None:
        calls.append(("message", scheduler))

    class FakeActivityService:
        async def schedule_reminders(self, scheduler: object) -> None:
            calls.append(("activity", scheduler))

    scheduler = FakeScheduler()
    activity_service = cast("ActivityService", FakeActivityService())
    messaging = _messaging_resources(tmp_path / "unsubscribe.sqlite")
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)
    option = PushTimeOption("test", "测试", "test", CRON_TIME_PREFERENCE, "", "")
    for preference_type in (
        CRON_TIME_PREFERENCE,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
    ):
        asyncio.run(
            messaging.refresh_push_time_jobs(
                replace(option, preference_type=preference_type),
                scheduler=scheduler,
                activity_service=activity_service,
            )
        )

    assert calls == [("message", scheduler), ("activity", scheduler)]


def test_push_subscription_menu_prompt_marks_current_state(tmp_path: Path) -> None:
    options = [
        PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
        PushSubscriptionOption(
            "startup_data_sync",
            "启动数据同步通知",
            "admin_notice",
            unsubscribed=True,
        ),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _target_type, _target_id: options,
    )
    _, prompt = messaging.subscription_menu(
        "private",
        1001,
    )

    assert "请选择要切换的推送订阅：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "2. ❌ 启动数据同步通知" in prompt
    assert "输入序号切换" in prompt


def test_push_subscription_menu_prompt_can_be_read_only(tmp_path: Path) -> None:
    options = [
        PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _target_type, _target_id: options,
    )
    _, prompt = messaging.subscription_menu(
        "group",
        1001,
        read_only=True,
    )

    assert "推送订阅状态：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "普通群员仅可查看" in prompt
    assert "输入序号切换" not in prompt


def test_push_subscription_menu_keeps_read_only_options_when_names_fail(
    tmp_path: Path,
) -> None:
    warning = "⚠️ 暂时无法刷新公开昵称，使用 UID 显示。"

    async def prepare(_target_type: PushTargetType, _target_id: int) -> str:
        return warning

    options = [
        PushSubscriptionOption(
            "bili_push:123",
            "B站动态（UID：123）",
            "bili_push",
        ),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _target_type, _target_id: options,
        prepare_extra_push_options=prepare,
    )

    resolved_options, prompt = asyncio.run(
        messaging.prepared_subscription_menu(
            "group",
            1001,
            read_only=True,
        )
    )

    assert resolved_options == options
    assert prompt.startswith(warning)
    assert "1. ✅ B站动态（UID：123）" in prompt
    assert "普通群员仅可查看" in prompt


def test_group_push_subscription_command_allows_superuser_member(
    tmp_path: Path,
) -> None:
    assert matcher_rules.match_push_subscription_command(
        _group_event(),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
    )


def test_group_push_subscription_command_allows_regular_member_to_view(
    tmp_path: Path,
) -> None:
    assert matcher_rules.match_push_subscription_command(
        _group_event(),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
    )


def test_group_push_subscription_management_command_matches_regular_member(
    tmp_path: Path,
) -> None:
    assert matcher_rules.match_push_subscription_command(
        _group_event("推送管理", user_id=3003),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
    )


def test_unified_command_action_uses_feature_policy_for_each_message_scope(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        commands=[
            MessageCommandAction(
                id="activity_link",
                commands=["activity"],
                feature="web_activity_link",
                message="activity link",
                at_user_ids=[3001],
            )
        ],
        user_policy={"2001": ["web_activity_link"]},
        group_policy={"1001": ["web_activity_link"]},
    )

    private_state: dict[str, object] = {}
    group_state: dict[str, object] = {}
    assert matcher_rules.match_message_command(
        private_message_event("activity", user_id=2001),
        private_state,
        messaging=messaging,
    )
    assert matcher_rules.match_message_command(
        group_member_message_event("activity", user_id=2002, group_id=1001),
        group_state,
        messaging=messaging,
    )
    private_action = cast(
        "MessageCommandAction",
        private_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    group_action = cast(
        "MessageCommandAction",
        group_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    assert private_action.id == "activity_link"
    assert group_action.at_user_ids == [3001]


def test_keyword_reply_uses_feature_policy_after_exact_commands(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        commands=[
            MessageCommandAction(
                id="exact_reply",
                commands=["出出"],
                feature="text",
                message="精确回复",
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="keyword_reply",
                keywords=["出出"],
                feature="text",
                message="关键词回复",
            )
        ],
        group_policy={"1001": ["text"]},
    )

    exact_state: dict[str, object] = {}
    keyword_state: dict[str, object] = {}
    assert matcher_rules.match_message_command(
        group_member_message_event("出出", user_id=2002, group_id=1001),
        exact_state,
        messaging=messaging,
    )
    assert matcher_rules.match_message_command(
        group_member_message_event("今天出出了", user_id=2002, group_id=1001),
        keyword_state,
        messaging=messaging,
    )
    exact_action = cast(
        "MessageCommandAction",
        exact_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    keyword_action = cast(
        "MessageKeywordReplyAction",
        keyword_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    assert exact_action.id == "exact_reply"
    assert keyword_action.id == "keyword_reply"


def test_group_mention_reply_requires_only_configured_user(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        mention_replies=[
            MessageMentionReplyAction(
                id="example_user_mention",
                user_ids=[2002],
                message="123",
            )
        ],
    )
    state: dict[str, object] = {}

    assert matcher_rules.match_group_mention_reply(
        group_member_message_event("", user_id=2002, group_id=1001),
        state,
        messaging=messaging,
    )
    assert not matcher_rules.match_group_mention_reply(
        group_member_message_event("", user_id=2003, group_id=1001),
        {},
        messaging=messaging,
    )
    action = cast(
        "MessageMentionReplyAction",
        state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    assert action.message == "123"


def test_unified_schedule_delivers_to_private_and_group_targets(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[dict[str, object]] = []
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push"]},
    )

    async def fake_broadcast(
        _delivery: object,
        _message: str,
        **kwargs: object,
    ) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_broadcast)
    asyncio.run(
        message_schedules.send_schedule(
            _schedule("shared schedule", at_user_ids=[3001]),
            messaging=messaging,
        )
    )

    assert sent[0]["private_user_ids"] == [2001]
    assert sent[0]["subscription_key"] == "daily"
    assert sent[1]["group_ids"] == [1001]
    assert sent[1]["group_at_user_ids"] == [3001]
    assert sent[1]["subscription_key"] == "daily"


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
        private_user_ids = kwargs.get("private_user_ids")
        if limiter is not None and isinstance(group_ids, list) and group_ids:
            message = limiter(message, MessageTarget("group", group_ids[0]))  # type: ignore[operator]
        if (
            limiter is not None
            and isinstance(private_user_ids, list)
            and private_user_ids
        ):
            message = limiter(  # type: ignore[operator]
                message,
                MessageTarget("private", private_user_ids[0]),
            )
        sent.append((message, kwargs))

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_send_broadcast_message)
    asyncio.run(
        message_schedules.send_private_schedule(
            _schedule("私聊定时", schedule_id="private"),
            messaging=messaging,
        )
    )
    asyncio.run(
        message_schedules.send_group_schedule(
            _schedule("群定时", at_user_ids=[3001], schedule_id="group"),
            messaging=messaging,
        )
    )

    assert [message for message, _kwargs in sent] == [
        "私聊定时",
        f"群定时\n\n{FIRE_MANUAL_LINK_MESSAGE}",
    ]
    assert sent[0][1]["private_user_ids"] == [2001]
    assert sent[0][1]["subscription_key"] == "private"
    assert sent[1][1]["group_ids"] == [1001]
    assert sent[1][1]["group_at_user_ids"] == [3001]
    assert sent[1][1]["subscription_key"] == "group"


def test_private_scheduled_message_appends_fire_manual_ad_only_when_enabled(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[str] = []
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push", "fire_manual_ad"]},
    )

    async def fake_broadcast(
        _delivery: object,
        message: str,
        **kwargs: object,
    ) -> None:
        limiter = kwargs.get("message_limiter")
        if limiter is not None:
            message = limiter(message, MessageTarget("private", 2001))  # type: ignore[operator]
        sent.append(message)

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_broadcast)
    asyncio.run(
        message_schedules.send_private_schedule(
            _schedule("私聊定时", schedule_id="private"),
            messaging=messaging,
        )
    )

    assert sent == [f"私聊定时\n\n{FIRE_MANUAL_LINK_MESSAGE}"]


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

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_send_broadcast_message)
    asyncio.run(
        message_schedules.send_private_schedule(
            _schedule("私聊定时", schedule_id="private"),
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
    store = PushUnsubscribeStore(data_path)
    messaging = _messaging_resources(
        data_path,
        group_policy={
            "1001": ["text_push"],
            "1002": ["text_push"],
        },
        store=store,
    )
    store.set_time_preference(
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

    monkeypatch.setattr(OneBotDelivery, "broadcast", fake_send_broadcast_message)
    asyncio.run(
        message_schedules.send_group_schedule(
            _schedule("group push", at_user_ids=[], schedule_id="daily"),
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
    task = MessageScheduledAction(
        message="group push",
        at_user_ids=[],
        id="daily",
        time="23:00",
    )
    scheduler = FakeScheduler()

    asyncio.run(
        message_schedules.register_message_schedules(
            scheduler,
            _messaging_resources(
                data_path,
                schedules=[task],
                group_policy={
                    "1001": ["text_push"],
                    "1002": ["text_push"],
                },
            ),
        )
    )

    assert [job["id"] for job in scheduler.jobs] == [
        "message_action_schedule_daily",
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
