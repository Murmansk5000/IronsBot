from pathlib import Path

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageConfig, MessageScheduledAction
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.subscriptions import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
from tests.helpers.runtime import build_test_runtime

REMOVED_PREFERENCE_COUNT = 2


def test_private_td_time_and_preferences_follow_selected_bot(tmp_path: Path) -> None:
    actor = ActorRef(Platform.ONEBOT, "123456")
    source = ConversationRef(Platform.ONEBOT, "private", actor.id)
    local = ConversationRef(
        Platform.QQ_OFFICIAL, "private", "local-user", account_id="local-app"
    )
    public = ConversationRef(
        Platform.QQ_OFFICIAL, "private", "public-user", account_id="public-app"
    )
    principals = IdentityPrincipalService()
    routes = PrivateConversationRoutes(
        onebot_enabled=False,
        official_accounts=frozenset({"local-app", "public-app"}),
        default_account="local-app",
    )
    for endpoint in (local, public):
        link = CrossPlatformIdentityLink(
            actor.id,
            OfficialIdentity(endpoint.account_id or "", "user", endpoint.id),
            1,
        )
        principals.register_private_link(link)
        routes.register(link)

    store = PushUnsubscribeStore(
        tmp_path / "subscriptions.sqlite",
        principal_for=principals.conversation_principal,
    )
    features = FeatureService(
        {},
        {actor: frozenset({"admin_notice", "seer_activity_push", "text_push"})},
        frozenset(),
    )
    config = MessageConfig(
        schedules=[
            MessageScheduledAction(id="daily", messages=["reminder"], time="12:00")
        ]
    )
    runtime = build_test_runtime()

    def extra(conversation: ConversationRef) -> list[PushSubscriptionOption]:
        return (
            [PushSubscriptionOption("bili:test", "B站动态", "bili_push")]
            if conversation == routes.selected_for(source)
            else []
        )

    messaging = MessagingService(
        config,
        ActivityConfig(),
        store,
        features,
        ScheduledMessageOutboundSender(runtime.proactive_delivery),
        build_onebot_message_schedule_targets(config, runtime.onebot_references),
        (extra,),
        _private_routes=routes,
    )
    local_options = messaging.subscription_options(local)
    assert {item.key for item in local_options} >= {
        "bili:test",
        "seer_activity_push",
        "startup_notice",
        "daily",
    }
    assert messaging.subscription_options(public) == []
    assert messaging.subscription_options(source) == []
    assert {item.key for item in messaging.push_time_options(local)} == {
        "seer_activity_push",
        "daily",
    }
    assert messaging.push_time_options(public) == []

    store.unsubscribe(local, "seer_activity_push", "seer_activity_push")
    store.unsubscribe(local, "removed", "text_push")
    store.set_time_preference(local, "daily", CRON_TIME_PREFERENCE, "13:00")
    store.set_time_preference(local, "removed", CRON_TIME_PREFERENCE, "14:00")
    routes.preferred_accounts[actor.id] = "public-app"
    assert messaging.subscription_options(local) == []
    assert next(
        item
        for item in messaging.subscription_options(public)
        if item.key == "seer_activity_push"
    ).unsubscribed
    assert (
        next(
            item for item in messaging.push_time_options(public) if item.key == "daily"
        ).current_value
        == "13:00"
    )
    assert (
        messaging._prune_stale_preferences().total_deleted == REMOVED_PREFERENCE_COUNT
    )
    assert not store.is_unsubscribed(source, "removed")

    routes.unregister(
        CrossPlatformIdentityLink(
            actor.id, OfficialIdentity("public-app", "user", public.id), 1
        )
    )
    assert messaging.subscription_options(local) == []
    assert messaging._prune_stale_preferences().total_deleted == 0
    assert store.is_unsubscribed(source, "seer_activity_push")
    assert store.get_time_preference(source, "daily", CRON_TIME_PREFERENCE) == "13:00"
