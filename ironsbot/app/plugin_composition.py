# SPDX-License-Identifier: MIT
"""Explicit composition of built-in business contributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.plugins.onebot.about import plugin_contribution as about_contribution
from ironsbot.plugins.onebot.activity import (
    plugin_contribution as activity_contribution,
)
from ironsbot.plugins.onebot.ai import plugin_contribution as ai_contribution
from ironsbot.plugins.onebot.ai.intent import (
    plugin_contribution as ai_intent_contribution,
)
from ironsbot.plugins.onebot.bilibili import (
    plugin_contribution as bilibili_contribution,
)
from ironsbot.plugins.onebot.clock_check import (
    plugin_contribution as clock_check_contribution,
)
from ironsbot.plugins.onebot.fire_manual_ad import (
    plugin_contribution as fire_manual_ad_contribution,
)
from ironsbot.plugins.onebot.headless_seer_notice import (
    plugin_contribution as headless_seer_notice_contribution,
)
from ironsbot.plugins.onebot.headless_seer_runtime import (
    plugin_contribution as headless_seer_runtime_contribution,
)
from ironsbot.plugins.onebot.help import plugin_contribution as help_contribution
from ironsbot.plugins.onebot.lucky_skin_window import (
    plugin_contribution as lucky_skin_window_contribution,
)
from ironsbot.plugins.onebot.messaging import (
    plugin_contribution as messaging_contribution,
)
from ironsbot.plugins.onebot.messaging.blacklist import (
    plugin_contribution as messaging_blacklist_contribution,
)
from ironsbot.plugins.onebot.messaging.meeting import (
    plugin_contribution as messaging_meeting_contribution,
)
from ironsbot.plugins.onebot.messaging.poke import (
    plugin_contribution as messaging_poke_contribution,
)
from ironsbot.plugins.onebot.messaging.red_packet import (
    plugin_contribution as messaging_red_packet_contribution,
)
from ironsbot.plugins.onebot.operations.db_sync import (
    plugin_contribution as operations_db_sync_contribution,
)
from ironsbot.plugins.onebot.operations.docker_update import (
    plugin_contribution as operations_docker_update_contribution,
)
from ironsbot.plugins.onebot.operations.server_status import (
    plugin_contribution as operations_server_status_contribution,
)
from ironsbot.plugins.onebot.pet_config import (
    plugin_contribution as pet_config_contribution,
)
from ironsbot.plugins.onebot.scheduled_restart import (
    plugin_contribution as scheduled_restart_contribution,
)
from ironsbot.plugins.onebot.seer.query import (
    plugin_contribution as seer_query_contribution,
)
from ironsbot.plugins.onebot.seer.rank_help import (
    plugin_contribution as seer_rank_help_contribution,
)
from ironsbot.plugins.onebot.sendpic import plugin_contribution as sendpic_contribution
from ironsbot.plugins.onebot.startup_notice import (
    plugin_contribution as startup_notice_contribution,
)
from ironsbot.plugins.onebot.team_audit import (
    plugin_contribution as team_audit_contribution,
)
from ironsbot.plugins.onebot.team_resource import (
    plugin_contribution as team_resource_contribution,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.app.resources import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.integrations.scheduler.facade import SchedulerFacade


@dataclass(frozen=True, slots=True)
class _ContributionFactory:
    build: Callable[[], PluginContribution]
    core: bool = False


def build_builtin_contributions(
    settings: Settings, resources: ApplicationResources, scheduler: SchedulerFacade
) -> tuple[PluginContribution, ...]:
    """Build only the selected profile, in one authoritative lifecycle order."""

    factories = (
        _ContributionFactory(
            lambda: clock_check_contribution(
                startup_check=resources.clock_startup_check
            )
        ),
        _ContributionFactory(
            lambda: seer_query_contribution(resources=resources, scheduler=scheduler),
            core=True,
        ),
        _ContributionFactory(
            lambda: bilibili_contribution(
                monitor=resources.bilibili_monitor, scheduler=scheduler
            )
        ),
        _ContributionFactory(
            lambda: messaging_contribution(
                config=settings.messaging,
                features=resources.features,
                service=resources.messaging,
                scheduler=scheduler,
            )
        ),
        _ContributionFactory(
            lambda: ai_contribution(
                settings=settings,
                features=resources.features,
                startup_check=resources.ai_startup_check,
            )
        ),
        _ContributionFactory(
            lambda: ai_intent_contribution(
                settings=settings, features=resources.features
            )
        ),
        _ContributionFactory(operations_server_status_contribution),
        _ContributionFactory(
            lambda: operations_docker_update_contribution(
                features=resources.features, startup_notice=resources.startup_notice
            )
        ),
        _ContributionFactory(
            lambda: operations_db_sync_contribution(features=resources.features)
        ),
        _ContributionFactory(about_contribution, core=True),
        _ContributionFactory(help_contribution, core=True),
        _ContributionFactory(messaging_poke_contribution, core=True),
        _ContributionFactory(lambda: sendpic_contribution(service=resources.sendpic)),
        _ContributionFactory(messaging_blacklist_contribution),
        _ContributionFactory(
            lambda: messaging_meeting_contribution(
                commands=tuple(settings.messaging.meeting.commands)
            )
        ),
        _ContributionFactory(messaging_red_packet_contribution),
        _ContributionFactory(fire_manual_ad_contribution),
        _ContributionFactory(
            lambda: seer_rank_help_contribution(
                player_id_resolver=resources.player_id_resolver
            ),
            core=True,
        ),
        _ContributionFactory(
            lambda: pet_config_contribution(
                features=resources.features,
                config=settings.pet_config,
                image_command_texts=resources.sendpic.exact_command_texts,
            )
        ),
        _ContributionFactory(
            lambda: lucky_skin_window_contribution(
                resources.lucky_skin_window,
                resources.features,
                scheduler,
                resources.player_id_resolver,
            )
        ),
        _ContributionFactory(
            lambda: team_audit_contribution(
                scheduler=scheduler, service=resources.team_audit
            )
        ),
        _ContributionFactory(
            lambda: team_resource_contribution(
                config=settings.seer.team_resource,
                features=resources.features,
                scheduler=scheduler,
                service=resources.team_resource,
            )
        ),
        _ContributionFactory(
            lambda: activity_contribution(
                service=resources.activity, scheduler=scheduler
            )
        ),
        _ContributionFactory(
            lambda: startup_notice_contribution(
                service=resources.startup_notice,
                config=settings.operations.startup_notice,
            )
        ),
        _ContributionFactory(
            lambda: headless_seer_notice_contribution(
                scheduler=scheduler, service=resources.headless
            )
        ),
        _ContributionFactory(
            lambda: headless_seer_runtime_contribution(service=resources.headless)
        ),
        _ContributionFactory(
            lambda: scheduled_restart_contribution(
                scheduler=scheduler, service=resources.scheduled_restart
            )
        ),
    )
    return tuple(
        entry.build()
        for entry in factories
        if settings.bot.plugin_manifest == "full" or entry.core
    )
