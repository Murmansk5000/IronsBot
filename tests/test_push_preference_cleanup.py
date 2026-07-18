from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.message import MessageConfig, PushUnsubscribeConfig
from ironsbot.plugins.messaging import preference_cleanup
from ironsbot.plugins.messaging.push_time import PushTimeOption
from ironsbot.plugins.messaging.runtime_service import MessagingResources
from ironsbot.shared.messaging.push_subscription_models import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore
from tests.helpers.runtime import build_test_runtime


def test_cleanup_uses_current_subscription_and_time_catalogs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "push_preferences.sqlite"
    store = PushUnsubscribeStore(data_path)
    store.unsubscribe_target("group", 2001, "daily", "text_push")
    store.unsubscribe_target("group", 2001, "removed", "text_push")
    store.set_time_preference(
        "group",
        2001,
        "daily",
        CRON_TIME_PREFERENCE,
        "22:30",
    )
    store.set_time_preference(
        "group",
        2001,
        "removed",
        CRON_TIME_PREFERENCE,
        "21:30",
    )

    monkeypatch.setattr(
        preference_cleanup,
        "build_messaging_push_subscription_options",
        lambda *_args, **_kwargs: [
            PushSubscriptionOption("daily", "每日提醒", "text_push")
        ],
    )
    monkeypatch.setattr(
        preference_cleanup,
        "build_push_time_options",
        lambda *_args, **_kwargs: [
            PushTimeOption(
                key="daily",
                label="每日提醒",
                feature="text_push",
                preference_type=CRON_TIME_PREFERENCE,
                default_value="23:00",
                current_value="22:30",
                overridden=True,
            )
        ],
    )

    runtime = build_test_runtime()
    messaging = MessagingResources(
        MessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path))
        ),
        ActivityConfig(),
        store,
        runtime.features,
        runtime.priority,
        runtime.delivery,
    )
    result = preference_cleanup.prune_stale_push_preferences(messaging)

    assert result.unsubscriptions_deleted == 1
    assert result.time_preferences_deleted == 1
    assert store.target_unsubscribed_keys("group", 2001) == {"daily"}
    assert (
        store.get_time_preference(
            "group",
            2001,
            "daily",
            CRON_TIME_PREFERENCE,
        )
        == "22:30"
    )
