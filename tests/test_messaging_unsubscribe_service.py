from dataclasses import dataclass
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message

from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.shared.messaging.push_subscriptions import (
    BUILTIN_PUSH_OPTIONS,
    PushUnsubscribeStore,
    append_push_unsubscribe_hint,
    build_schedule_subscription_options,
    group_schedule_label,
    private_schedule_key,
    private_schedule_label,
)


@dataclass(frozen=True, slots=True)
class FakePrivateSchedule:
    id: str
    feature: str
    name: str = ""
    message: str = "消息"
    hour: int = 23
    minute: int = 0
    day_of_week: str | None = None
    enabled: bool = True


def test_private_schedule_key_prefers_id_and_falls_back_to_job_id() -> None:
    assert (
        private_schedule_key(2, FakePrivateSchedule(id="daily", feature="push"))
        == "daily"
    )
    assert (
        private_schedule_key(2, FakePrivateSchedule(id="", feature="push"))
        == "message_action_private_schedule_task_2"
    )


def test_schedule_label_uses_configured_name_before_internal_id() -> None:
    task = FakePrivateSchedule(
        id="activity_link_daily_private",
        name="周年庆签到提醒",
        feature="web_activity_push",
    )

    assert private_schedule_label(1, task) == "周年庆签到提醒（23:00）"


def test_schedule_label_derives_name_from_message_before_internal_id() -> None:
    task = FakePrivateSchedule(
        id="activity_link_daily_private",
        feature="web_activity_push",
        message="周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign",
    )

    assert private_schedule_label(1, task) == "周年庆主题站签到活动（23:00）"


def test_schedule_label_falls_back_to_feature_name_without_feature_leak() -> None:
    task = FakePrivateSchedule(
        id="activity_link_daily_private",
        feature="web_activity_push",
        message="https://seerm.61.com/events/17years/#sign",
    )

    assert group_schedule_label(1, task) == "游戏外活动推送（23:00）"


def test_builtin_push_options_split_startup_admin_notices() -> None:
    labels = {option.key: option.label for option in BUILTIN_PUSH_OPTIONS}

    assert labels["startup_notice"] == "机器人启动通知"
    assert labels["startup_docker_update"] == "启动镜像检查通知"
    assert labels["startup_data_sync"] == "启动数据同步通知"
    assert labels["admin_notice"] == "其他管理通知"


def test_append_push_unsubscribe_hint_is_last_line() -> None:
    config = PushUnsubscribeConfig(
        hint="回复 TD 可退订。",
        group_hint="管理员发送 TD 可退订。",
    )

    assert append_push_unsubscribe_hint(
        "正文\n\n广告",
        config,
        target_type="private",
    ) == (
        "正文\n\n广告\n\n回复 TD 可退订。"
    )
    assert append_push_unsubscribe_hint(
        "正文\n\n回复 TD 可退订。",
        config,
        target_type="private",
    ) == "正文\n\n回复 TD 可退订。"
    assert (
        str(
            append_push_unsubscribe_hint(
                Message("正文"),
                config,
                target_type="group",
            )
        )
        == "正文\n\n管理员发送 TD 可退订。"
    )


def test_store_unsubscribe_restore_and_filter(tmp_path: Path) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    store.unsubscribe_target("private", 1001, "daily", "text_push")
    store.unsubscribe_target("group", 2001, "bili_push", "bili_push")

    assert store.is_target_unsubscribed("private", 1001, "daily")
    assert store.target_unsubscribed_keys("private", 1001) == {"daily"}
    assert store.filter_subscribed_user_ids([1001, 1002, 1001], "daily") == [1002]
    assert store.is_target_unsubscribed("group", 2001, "bili_push")
    assert store.filter_subscribed_group_ids([2001, 2002], "bili_push") == [2002]

    store.restore_target("private", 1001, "daily")
    store.restore_target("group", 2001, "bili_push")

    assert not store.is_target_unsubscribed("private", 1001, "daily")
    assert store.filter_subscribed_user_ids([1001, 1002], "daily") == [1001, 1002]
    assert store.filter_subscribed_group_ids([2001, 2002], "bili_push") == [
        2001,
        2002,
    ]


def test_build_schedule_subscription_options_splits_available_and_restorable(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    tasks = [
        FakePrivateSchedule(id="daily", feature="text_push"),
        FakePrivateSchedule(id="weekly", feature="weekly_push"),
        FakePrivateSchedule(id="disabled", feature="text_push", enabled=False),
    ]
    eligible = {
        "text_push": {1001},
        "weekly_push": {1001},
    }
    store.unsubscribe_target("private", 1001, "daily", "text_push")

    available = build_schedule_subscription_options(
        target_type="private",
        target_id=1001,
        tasks=tasks,
        eligible_target_ids_for_feature=eligible,
        store=store,
        include_unsubscribed=False,
    )
    restorable = build_schedule_subscription_options(
        target_type="private",
        target_id=1001,
        tasks=tasks,
        eligible_target_ids_for_feature=eligible,
        store=store,
        include_unsubscribed=True,
    )

    assert [option.key for option in available] == ["weekly"]
    assert [option.key for option in restorable] == ["daily"]
