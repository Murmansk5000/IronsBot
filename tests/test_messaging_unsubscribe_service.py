import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.push_subscriptions import (
    PUSH_SUBSCRIPTION_SCHEMA,
    PushUnsubscribeStore,
)
from ironsbot.services.identity_link_store import CrossPlatformGroupLink
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.subscription_options import (
    build_push_subscription_menu,
    build_schedule_subscription_options,
    schedule_key,
    schedule_label,
)
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    BUILTIN_PUSH_OPTIONS,
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)

EXPECTED_PRUNED_UNSUBSCRIPTIONS = 2
EXPECTED_PRUNED_TIME_PREFERENCES = 2
EXPECTED_PRUNED_TOTAL = 4


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _official_group(app_id: str, group_openid: str) -> ConversationRef:
    return ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        group_openid,
        account_id=app_id,
    )


@dataclass(frozen=True, slots=True)
class FakeSchedule:
    id: str
    feature: str
    name: str = ""
    messages: list[str] = field(default_factory=lambda: ["消息"])
    time: str = "23:00"
    day_of_week: str | None = None
    enabled: bool = True


def test_schedule_key_requires_stable_id() -> None:
    assert schedule_key(2, FakeSchedule(id="daily", feature="push")) == "daily"
    with pytest.raises(ValueError, match="requires a stable id"):
        schedule_key(2, FakeSchedule(id="", feature="push"))


def test_schedule_label_uses_configured_name_before_internal_id() -> None:
    task = FakeSchedule(
        id="web_activity_daily_private",
        name="周年庆签到提醒",
        feature="web_activity_push",
    )

    assert schedule_label(1, task) == "周年庆签到提醒（23:00）"


def test_schedule_label_derives_name_from_message_before_internal_id() -> None:
    task = FakeSchedule(
        id="web_activity_daily_private",
        feature="web_activity_push",
        messages=["周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign"],
    )

    assert schedule_label(1, task) == "周年庆主题站签到活动（23:00）"


def test_schedule_label_falls_back_to_feature_name_without_feature_leak() -> None:
    task = FakeSchedule(
        id="web_activity_daily_private",
        feature="web_activity_push",
        messages=["https://seerm.61.com/events/17years/#sign"],
    )

    assert schedule_label(1, task) == "游戏外活动推送（23:00）"


def test_builtin_push_options_split_startup_admin_notices() -> None:
    labels = {option.key: option.label for option in BUILTIN_PUSH_OPTIONS}

    assert labels["startup_notice"] == "机器人启动通知"
    assert labels["startup_docker_update"] == "启动镜像检查通知"
    assert labels["startup_data_sync"] == "启动数据同步通知"
    assert labels["startup_clock_check"] == "启动时钟偏差检查通知"
    assert labels["ai_chat_error_notice"] == "AI聊天异常通知"
    assert labels["bili_login_notice"] == "B站登录通知"
    assert labels["headless_seer_notice"] == "无头赛尔号通知"
    assert labels["render_crash_notice"] == "精灵渲染崩溃通知"
    assert labels["red_packet_notice"] == "红包提醒"
    assert labels["admin_notice"] == "其他管理通知"


def test_store_unsubscribe_restore_and_filter(tmp_path: Path) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    store.unsubscribe(_private(1001), "daily", "text_push")
    store.unsubscribe(_group(2001), "bili_push", "bili_push")

    assert store.is_unsubscribed(_private(1001), "daily")
    assert store.unsubscribed_keys(_private(1001)) == {"daily"}
    assert store.filter_subscribed_conversations(
        [_private(1001), _private(1002), _private(1001)],
        "daily",
    ) == [_private(1002)]
    assert store.is_unsubscribed(_group(2001), "bili_push")
    assert store.filter_subscribed_conversations(
        [_group(2001), _group(2002)],
        "bili_push",
    ) == [_group(2002)]

    store.restore(_private(1001), "daily")
    store.restore(_group(2001), "bili_push")

    assert not store.is_unsubscribed(_private(1001), "daily")
    assert store.filter_subscribed_conversations(
        [_private(1001), _private(1002)],
        "daily",
    ) == [_private(1001), _private(1002)]
    assert store.filter_subscribed_conversations(
        [_group(2001), _group(2002)],
        "bili_push",
    ) == [
        _group(2001),
        _group(2002),
    ]


def test_store_daily_hint_marker_is_per_target_and_day(tmp_path: Path) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    assert store.mark_daily_hint_sent(
        _group(2001),
        "push_subscription_hint",
        today="2026-07-09",
    )
    assert not store.mark_daily_hint_sent(
        _group(2001),
        "push_subscription_hint",
        today="2026-07-09",
    )
    assert store.mark_daily_hint_sent(
        _group(2002),
        "push_subscription_hint",
        today="2026-07-09",
    )
    assert store.mark_daily_hint_sent(
        _group(2001),
        "push_subscription_hint",
        today="2026-07-10",
    )


def test_group_principal_merge_unifies_push_state_and_preserves_endpoint(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    path = tmp_path / "unsubscribe.sqlite"
    store = PushUnsubscribeStore(
        path,
        principal_for=principals.conversation_principal,
    )
    onebot = _group(2001)
    official_a = _official_group("app-a", "group-a")
    official_b = _official_group("app-b", "group-b")

    store.unsubscribe(onebot, "onebot-only", "text_push")
    store.unsubscribe(official_a, "official-only", "bili_push")
    store.set_time_preference(
        onebot,
        "daily",
        CRON_TIME_PREFERENCE,
        "21:00",
    )
    store.set_time_preference(
        official_a,
        "daily",
        CRON_TIME_PREFERENCE,
        "22:00",
    )
    assert store.mark_daily_hint_sent(
        onebot,
        "push_subscription_hint",
        today="2026-07-09",
    )
    assert store.mark_daily_hint_sent(
        official_a,
        "push_subscription_hint",
        today="2026-07-10",
    )

    for link in (
        CrossPlatformGroupLink("2001", "app-a", "group-a", 1.0),
        CrossPlatformGroupLink("2001", "app-b", "group-b", 2.0),
    ):
        for merge in principals.register_group_link(link):
            store.merge_principals(merge.source, merge.target)

    for conversation in (onebot, official_a, official_b):
        assert store.unsubscribed_keys(conversation) == {
            "onebot-only",
            "official-only",
        }
        assert (
            store.get_time_preference(
                conversation,
                "daily",
                CRON_TIME_PREFERENCE,
            )
            == "22:00"
        )
        assert not store.mark_daily_hint_sent(
            conversation,
            "push_subscription_hint",
            today="2026-07-10",
        )

    preferences = store.all_time_preferences(
        subscription_key="daily",
        preference_type=CRON_TIME_PREFERENCE,
    )
    assert len(preferences) == 1
    assert preferences[0].conversation == official_a

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM push_unsubscriptions "
            "WHERE principal_kind = 'official_group'"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_v2_push_state_migrates_to_principal_ownership(tmp_path: Path) -> None:
    path = tmp_path / "unsubscribe.sqlite"
    with sqlite3.connect(path) as connection:
        for statement in PUSH_SUBSCRIPTION_SCHEMA:
            connection.execute(statement)
        connection.execute(
            """
            CREATE TABLE ironsbot_schema_migrations (
                namespace TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO ironsbot_schema_migrations VALUES "
            "('push_subscriptions', 2, '2026-07-09T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO push_unsubscriptions VALUES "
            "('onebot', '', 'group', '2001', 'daily', 'text_push', "
            "'2026-07-09T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO push_time_preferences VALUES "
            "('onebot', '', 'group', '2001', 'daily', 'cron_time', '22:30', "
            "'2026-07-09T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO push_daily_hints VALUES "
            "('onebot', '', 'group', '2001', 'hint', '2026-07-09', "
            "'2026-07-09T00:00:00+00:00')"
        )

    store = PushUnsubscribeStore(path)

    assert store.is_unsubscribed(_group(2001), "daily")
    assert (
        store.get_time_preference(
            _group(2001),
            "daily",
            CRON_TIME_PREFERENCE,
        )
        == "22:30"
    )
    assert not store.mark_daily_hint_sent(
        _group(2001),
        "hint",
        today="2026-07-09",
    )
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(push_unsubscriptions)"
            ).fetchall()
        }
        assert {"principal_kind", "principal_id"} <= columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_store_time_preferences_set_filter_and_clear(tmp_path: Path) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    store.set_time_preference(
        _group(2001),
        "daily",
        CRON_TIME_PREFERENCE,
        "22:30",
    )
    store.set_time_preference(
        _private(1001),
        "seer_activity_push",
        ACTIVITY_LEAD_HOURS_PREFERENCE,
        "24,3,1",
    )

    assert (
        store.get_time_preference(_group(2001), "daily", CRON_TIME_PREFERENCE)
        == "22:30"
    )
    assert {
        (preference.subscription_key, preference.preference_type): preference.value
        for preference in store.all_time_preferences(
            conversation_kind="private",
        )
        if preference.conversation == _private(1001)
    } == {("seer_activity_push", ACTIVITY_LEAD_HOURS_PREFERENCE): "24,3,1"}
    assert [
        preference.conversation
        for preference in store.all_time_preferences(
            conversation_kind="group",
            subscription_key="daily",
            preference_type=CRON_TIME_PREFERENCE,
        )
    ] == [_group(2001)]

    store.clear_time_preference(_group(2001), "daily", CRON_TIME_PREFERENCE)

    assert (
        store.get_time_preference(_group(2001), "daily", CRON_TIME_PREFERENCE) is None
    )


def test_store_prunes_invalid_push_preferences_atomically(tmp_path: Path) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    store.unsubscribe(_group(2001), "daily", "text_push")
    store.unsubscribe(_group(2001), "removed", "text_push")
    store.unsubscribe(_private(1001), "orphaned", "text_push")
    store.set_time_preference(
        _group(2001),
        "daily",
        CRON_TIME_PREFERENCE,
        "22:30",
    )
    store.set_time_preference(
        _group(2001),
        "removed",
        CRON_TIME_PREFERENCE,
        "21:30",
    )
    store.set_time_preference(
        _private(1001),
        "orphaned",
        CRON_TIME_PREFERENCE,
        "20:30",
    )
    assert store.mark_daily_hint_sent(
        _group(2001),
        "push_subscription_hint",
        today="2026-07-17",
    )

    assert store.preference_conversations() == {
        _group(2001),
        _private(1001),
    }

    result = store.prune_invalid_preferences(
        valid_unsubscription_keys={
            _group(2001): {"daily"},
        },
        valid_time_preferences={
            _group(2001): {("daily", CRON_TIME_PREFERENCE)},
        },
    )

    assert result.unsubscriptions_deleted == EXPECTED_PRUNED_UNSUBSCRIPTIONS
    assert result.time_preferences_deleted == EXPECTED_PRUNED_TIME_PREFERENCES
    assert result.total_deleted == EXPECTED_PRUNED_TOTAL
    assert store.unsubscribed_keys(_group(2001)) == {"daily"}
    assert store.unsubscribed_keys(_private(1001)) == set()
    assert (
        store.get_time_preference(
            _group(2001),
            "daily",
            CRON_TIME_PREFERENCE,
        )
        == "22:30"
    )
    assert (
        store.get_time_preference(
            _group(2001),
            "removed",
            CRON_TIME_PREFERENCE,
        )
        is None
    )
    assert not store.mark_daily_hint_sent(
        _group(2001),
        "push_subscription_hint",
        today="2026-07-17",
    )


def test_build_schedule_subscription_options_marks_subscription_state(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    tasks = [
        FakeSchedule(id="daily", feature="text_push"),
        FakeSchedule(id="weekly", feature="weekly_push"),
        FakeSchedule(id="disabled", feature="text_push", enabled=False),
    ]
    conversation = _private(1001)
    eligible = {
        "text_push": {conversation},
        "weekly_push": {conversation},
    }
    store.unsubscribe(conversation, "daily", "text_push")

    options = build_schedule_subscription_options(
        conversation=conversation,
        tasks=tasks,
        eligible_conversations_for_feature=eligible,
        store=store,
    )

    assert [option.key for option in options] == ["daily", "weekly"]
    assert [option.unsubscribed for option in options] == [True, False]


def test_build_push_subscription_menu_shows_subscription_state() -> None:
    assert "server_status_push" not in {option.key for option in BUILTIN_PUSH_OPTIONS}

    options = [
        BUILTIN_PUSH_OPTIONS[0],
        PushSubscriptionOption(
            key=BUILTIN_PUSH_OPTIONS[1].key,
            label=BUILTIN_PUSH_OPTIONS[1].label,
            feature=BUILTIN_PUSH_OPTIONS[1].feature,
            unsubscribed=True,
        ),
    ]

    text = build_push_subscription_menu(
        title="请选择要切换的推送订阅：",
        options=options,
    )

    assert "✅ 活动结束提醒" in text
    assert "❌ 机器人启动通知" in text
    assert "0. 【退出】" in text
    assert "✅ 已订阅 · ❌ 已退订，输入序号切换" in text
