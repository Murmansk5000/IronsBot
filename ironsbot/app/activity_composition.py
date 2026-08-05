# SPDX-License-Identifier: MIT
"""Activity reminder assembly owned by application composition."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    private_conversation_for_actor,
)
from ironsbot.services.activity.delivery import (
    ActivityReminderDelivery,
    ActivityReminderSender,
    ActivityReminderTargets,
)
from ironsbot.services.activity.models import ActivityInfoCache
from ironsbot.services.activity.repository import ActivityRepository
from ironsbot.services.activity.service import (
    ACTIVITY_PUSH_SUBSCRIPTION_KEY,
    ActivityService,
)
from ironsbot.services.messaging.subscriptions import ACTIVITY_LEAD_HOURS_PREFERENCE

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.activity_notice import UnityNoticeSource
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_SEERAPI_DB_NAME = "seerapi"
_ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)
_SOON_ENDING_THRESHOLD = timedelta(days=7)


def build_activity_service(  # noqa: PLR0913 - composition root
    config: ActivityConfig,
    runtime_state_path: Path,
    features: FeatureService,
    sender: ActivityReminderSender,
    databases: DatabaseManager,
    subscriptions: PushSubscriptionRepository,
    notice_source: UnityNoticeSource,
) -> ActivityService:
    """Build the activity service from storage, policy, and delivery ports."""
    from ironsbot.integrations.storage.activity import ActivitySentStore

    sent_store = ActivitySentStore(runtime_state_path)
    repository = ActivityRepository()

    def load_rows():
        with databases.session(_SEERAPI_DB_NAME) as session:
            return repository.load(session, only_shown=config.only_shown)

    def preference_values():
        return (
            preference.value
            for preference in subscriptions.all_time_preferences(
                subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
                preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
            )
        )

    def preference_for_target(target: ActorRef | ConversationRef) -> str | None:
        if isinstance(target, ActorRef):
            try:
                conversation = private_conversation_for_actor(target)
            except ValueError:
                return None
        elif isinstance(target, ConversationRef):
            conversation = target
        else:
            return None
        return subscriptions.get_time_preference(
            conversation,
            ACTIVITY_PUSH_SUBSCRIPTION_KEY,
            ACTIVITY_LEAD_HOURS_PREFERENCE,
        )

    def targets() -> ActivityReminderTargets:
        return ActivityReminderTargets(
            group_conversations=tuple(
                features.conversations_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
            ),
            private_actors=tuple(
                features.actors_with_superusers(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
            ),
        )

    async def broadcast(reminder: ActivityReminderDelivery) -> bool:
        return await sender.send(reminder)

    return ActivityService(
        config=config,
        cache=ActivityInfoCache(),
        load_rows=load_rows,
        load_notice_text=notice_source.fetch,
        cache_ttl=_ACTIVITY_INFO_CACHE_TTL,
        soon_ending_threshold=_SOON_ENDING_THRESHOLD,
        filter_unsent=sent_store.filter_unsent,
        mark_sent=sent_store.mark_sent,
        preference_values=preference_values,
        preference_for_target=preference_for_target,
        targets=targets,
        broadcast=broadcast,
        now=lambda: datetime.now(_LOCAL_TZ),
    )
