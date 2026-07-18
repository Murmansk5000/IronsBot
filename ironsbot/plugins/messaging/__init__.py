from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.admin_priority import wait_for_superuser_priority
from ironsbot.shared.messaging import configure_reply_delivery_policy

from .matchers import install as install_matchers

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry

    from .push_time_handlers import RefreshPushTimeJobs
    from .runtime_service import MessagingResources


def install(
    registry: MatcherRegistry,
    refresh_push_time_jobs: RefreshPushTimeJobs,
    messaging: MessagingResources,
) -> None:
    configure_reply_delivery_policy(before_send=wait_for_superuser_priority)
    install_matchers(
        registry,
        refresh_push_time_jobs,
        messaging,
    )
