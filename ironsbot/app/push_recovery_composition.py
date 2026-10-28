# SPDX-License-Identifier: MIT
"""Wire persisted delivery policy after all public business services exist."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.daily_delivery import SqliteDailyDeliveryStore
from ironsbot.services.bilibili.delivery_recovery import BiliDeliveryRecovery
from ironsbot.services.messaging.delivery_recovery import ProactiveRecovery
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent
from ironsbot.services.seer.lucky_skin_window_recovery import LuckyWindowRecovery

if TYPE_CHECKING:
    from ironsbot.app.common_composition import CommonComponents
    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.app.seer_composition import SeerComponents
    from ironsbot.config.models.settings import Settings
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.messaging.delivery_tasks import StoredDelivery
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions


def build_push_recovery(  # noqa: PLR0913 - explicit application dependencies
    settings: Settings,
    common: CommonComponents,
    task_owner: TaskOwner,
    seer: SeerComponents,
    messaging: MessagingService,
    monitor: BilibiliMonitorService,
    sessions: PortableQuerySessions,
) -> ProactiveRecovery:
    assert common.proactive_delivery.outbox is not None

    async def notify(text: str) -> None:
        await common.admin_notices.send_private_to_superusers(
            text,
            action_name="proactive recovery summary",
            subscription_key="admin_notice",
            intent=DeliveryIntent(
                uuid.uuid4().hex,
                time.time() + 86400,
                feature="admin_notice",
                supersedes="proactive_recovery_summary",
            ),
        )

    if isinstance(monitor.delivery_recovery, BiliDeliveryRecovery):
        monitor.delivery_recovery.accounts = common.proactive_delivery.outbox

        async def notify_bilibili(dynamic_id: str, text: str) -> None:
            await common.admin_notices.send_private_to_superusers(
                text,
                action_name="Bilibili recovery summary",
                subscription_key="admin_notice",
                intent=DeliveryIntent(
                    uuid.uuid4().hex,
                    time.time() + 86400,
                    feature="admin_notice",
                    supersedes=f"bili_recovery:{dynamic_id}",
                ),
            )

        monitor.delivery_recovery.notify = notify_bilibili

    lucky = LuckyWindowRecovery(
        seer.lucky_skin_window,
        seer.seer.pet_query,
        common.features,
        sessions,
        SqliteDailyDeliveryStore(settings.paths.runtime_state),
    )

    def current(task: StoredDelivery) -> bool:
        if not lucky.allowed(task):
            return False
        if task.action.startswith(
            ("private scheduled message ", "group scheduled message ")
        ):
            return any(
                task.action.endswith(f"message {configured.id}") and configured.enabled
                for configured in settings.messaging.scheduled_actions
            )
        if task.subscription and task.subscription.startswith("push_topic:"):
            if messaging.topics is None:
                return False
            try:
                return messaging.topics.topic(
                    task.subscription.removeprefix("push_topic:")
                ).enabled
            except ValueError:
                return False
        return True

    return ProactiveRecovery(
        common.proactive_delivery,
        common.proactive_delivery.outbox,
        task_owner.create,
        notify=notify,
        additional=monitor.delivery_recovery,
        validate=current,
        prepare=lucky.prepare,
        finished=lucky.finished,
    )
