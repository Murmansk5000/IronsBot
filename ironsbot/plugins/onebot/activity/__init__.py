# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.core.features import Feature
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
    is_current_seer_activity_text,
    is_soon_ending_seer_activity_text,
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


def command_descriptors() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "activity",
            "查询",
            "seer_activity_query",
            (
                (
                    "activity.ending",
                    SOON_ENDING_ACTIVITY_COMMANDS[:1],
                    "查询即将结束的活动",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "activity",
            "超级管理员",
            "seer_activity_query",
            (
                (
                    "activity.current",
                    tuple(f"/{command}" for command in CURRENT_ACTIVITY_COMMANDS[:1]),
                    "查询完整活动列表",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
            ),
        ),
    )


async def _is_current_seer_activity_command(event: Event) -> bool:
    return is_current_seer_activity_text(event.get_plaintext())


async def _is_soon_ending_seer_activity_command(event: Event) -> bool:
    return is_soon_ending_seer_activity_text(event.get_plaintext())


def install(
    registry: MatcherFactory,
    service: ActivityService,
    features: FeatureService,
) -> None:
    async def handle_current(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.build_current_message(),
        )

    async def handle_soon_ending(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        await finish_event_reply(
            matcher,
            event,
            await service.build_current_message(soon_only=True),
        )

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
    current_matcher.append_handler(handle_current)

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
    ending_matcher.append_handler(handle_soon_ending)


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
        commands=command_descriptors(),
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
