# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.activity.command_contracts import activity_command_contracts
from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_new_seer_activity_text,
    is_soon_ending_seer_activity_text,
)
from ironsbot.services.portable_activity_commands import (
    build_portable_activity_operations,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.operations.scheduler import Scheduler

__plugin_meta__ = PluginMetadata(
    name="活动结束提醒",
    description="查询活动结束时间，并自动提醒即将结束的活动。",
    usage="发送“快结束活动”查看即将结束的活动。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


async def _is_new_seer_activity_command(event: Event) -> bool:
    return is_new_seer_activity_text(event.get_plaintext())


def install(
    registry: MatcherFactory,
    service: ActivityService,
    features: FeatureService,
) -> None:
    operations = build_portable_activity_operations(service)

    current_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "seer_activity_current",
            help_ids=("activity.current",),
        ),
        rule=Rule(_is_current_seer_activity_command) & explicit_command(),
        permission=SUPERUSER,
        priority=registry.priority("activity"),
        block=True,
    )
    current_matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["activity.current"],
        )
    )

    ending_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "seer_activity_ending",
            help_ids=("activity.ending",),
        ),
        rule=(
            Rule(
                lambda event: event_is_feature_allowed(
                    features, event, "seer_activity_query"
                )
            )
            & Rule(_is_soon_ending_seer_activity_command)
            & explicit_command()
        ),
        priority=registry.priority("activity"),
        block=True,
    )
    ending_matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["activity.ending"],
        )
    )

    new_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "seer_activity_new",
            help_ids=("activity.new",),
        ),
        rule=(
            Rule(
                lambda event: event_is_feature_allowed(
                    features, event, "seer_activity_query"
                )
            )
            & Rule(_is_new_seer_activity_command)
            & explicit_command()
        ),
        priority=registry.priority("activity"),
        block=True,
    )
    new_matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=operations["activity.new"],
        )
    )


def plugin_contribution(
    *,
    service: ActivityService,
    features: FeatureService,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare activity commands, matchers, and reminder scheduling."""

    return PluginContribution(
        id="activity",
        features=frozenset({Feature.SEER_ACTIVITY_QUERY, Feature.SEER_ACTIVITY_PUSH}),
        help=HelpEntry(
            name="活动结束提醒",
            description="读取活动结束时间并提前提醒即将结束的活动",
            group="message",
            order=10,
            notes=("自动提醒时间由 activity.lead_hours 配置。",),
        ),
        commands=activity_command_contracts(),
        install=partial(install, service=service, features=features),
        hooks=PluginHooks(
            startup=(
                (
                    "activity_reminder_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.activity,
            features=context.resources.features,
            scheduler=context.scheduler,
        ),
    )
