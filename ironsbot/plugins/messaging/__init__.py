from __future__ import annotations

from typing import TYPE_CHECKING

from .matchers import install as install_matchers
from .policies import setup_messaging_delivery_policies

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry

    from .push_time_handlers import RefreshPushTimeJobs


def install(
    registry: MatcherRegistry,
    refresh_push_time_jobs: RefreshPushTimeJobs,
) -> None:
    setup_messaging_delivery_policies()
    install_matchers(registry, refresh_push_time_jobs)
