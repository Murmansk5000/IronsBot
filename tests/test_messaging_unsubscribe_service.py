from dataclasses import dataclass
from pathlib import Path

from ironsbot.config.models.message import PrivateUnsubscribeConfig
from ironsbot.plugins.messaging.unsubscribe import (
    PrivatePushUnsubscribeStore,
    append_private_unsubscribe_hint,
    build_private_schedule_options,
    private_schedule_key,
)


@dataclass(frozen=True, slots=True)
class FakePrivateSchedule:
    id: str
    feature: str
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


def test_append_private_unsubscribe_hint_is_last_line() -> None:
    config = PrivateUnsubscribeConfig(hint="回复 TD 可退订。")

    assert append_private_unsubscribe_hint("正文\n\n广告", config) == (
        "正文\n\n广告\n\n回复 TD 可退订。"
    )
    assert append_private_unsubscribe_hint(
        "正文\n\n回复 TD 可退订。",
        config,
    ) == "正文\n\n回复 TD 可退订。"
    assert append_private_unsubscribe_hint(
        "正文",
        PrivateUnsubscribeConfig(enabled=False),
    ) == "正文"


def test_store_unsubscribe_restore_and_filter(tmp_path: Path) -> None:
    store = PrivatePushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    store.unsubscribe(1001, "daily", "text_push")

    assert store.is_unsubscribed(1001, "daily")
    assert store.unsubscribed_keys(1001) == {"daily"}
    assert store.filter_subscribed_user_ids([1001, 1002, 1001], "daily") == [1002]

    store.restore(1001, "daily")

    assert not store.is_unsubscribed(1001, "daily")
    assert store.filter_subscribed_user_ids([1001, 1002], "daily") == [1001, 1002]


def test_build_private_schedule_options_splits_available_and_restorable(
    tmp_path: Path,
) -> None:
    store = PrivatePushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    tasks = [
        FakePrivateSchedule(id="daily", feature="text_push"),
        FakePrivateSchedule(id="weekly", feature="weekly_push"),
        FakePrivateSchedule(id="disabled", feature="text_push", enabled=False),
    ]
    eligible = {
        "text_push": {1001},
        "weekly_push": {1001},
    }
    store.unsubscribe(1001, "daily", "text_push")

    available = build_private_schedule_options(
        user_id=1001,
        tasks=tasks,
        eligible_user_ids_for_feature=eligible,
        store=store,
        include_unsubscribed=False,
    )
    restorable = build_private_schedule_options(
        user_id=1001,
        tasks=tasks,
        eligible_user_ids_for_feature=eligible,
        store=store,
        include_unsubscribed=True,
    )

    assert [option.key for option in available] == ["weekly"]
    assert [option.key for option in restorable] == ["daily"]
