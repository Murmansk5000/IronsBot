# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import PluginContribution, PluginHooks

if TYPE_CHECKING:
    from ironsbot.core.platform import BotAccountRef
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.audit import TeamAuditService


async def restore_team_audit_followups(
    _account: BotAccountRef,
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    """Restore pending work when the OneBot connection becomes available."""

    await service.schedule_pending(scheduler)


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> PluginContribution:
    """Declare audit ownership and its follow-up lifecycle hooks."""

    return PluginContribution(
        id="team_audit",
        features=frozenset({Feature.TEAM_AUDIT}),
        hooks=PluginHooks(
            startup=(
                ("team_audit_followups", partial(service.start, scheduler=scheduler)),
            ),
            shutdown=(
                ("team_audit_followups", partial(service.stop, scheduler=scheduler)),
            ),
            bot_connect=(
                (
                    "team_audit_recovery",
                    partial(
                        restore_team_audit_followups,
                        scheduler=scheduler,
                        service=service,
                    ),
                ),
            ),
        ),
    )
