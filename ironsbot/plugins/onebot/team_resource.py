# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.app.plugin_visibility import feature_help_visible
from ironsbot.core.commands import parse_confirmation
from ironsbot.core.features import Feature
from ironsbot.runtime.commands import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.permissions import is_group_owner_or_admin_event
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.runtime.replies import finish_event_reply, finish_message_sequence
from ironsbot.runtime.rules import explicit_command, member_targets_command
from ironsbot.services.team.resource import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.resource import TeamResourceService

__plugin_meta__ = PluginMetadata(
    name="战队资源订阅",
    description="查询订阅战队的资源，并在资源不足时发送提醒。",
    usage="发送“战队”查看订阅；管理员可发送“订阅战队123456”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def command_descriptors(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "team_resource",
            "查询",
            "team_resource_subscription",
            (
                (
                    "team_resource.query",
                    ("战队",),
                    "查看当前会话订阅战队的信息和资源",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "team_resource",
            "订阅管理",
            "team_resource_subscription",
            (
                (
                    "team_resource.subscribe",
                    ("订阅战队123456",),
                    "订阅战队资源提醒；群聊可在末尾 @ 提醒对象",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
                (
                    "team_resource.unsubscribe",
                    ("取消订阅战队123456",),
                    "取消当前会话指定战队订阅",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
                (
                    "team_resource.list",
                    ("战队订阅",),
                    "查看和管理当前会话的战队订阅",
                    {
                        "access": (
                            CommandAccess("group", "group_manager"),
                            CommandAccess("private"),
                        ),
                        "show_in_poke": True,
                    },
                ),
            ),
        ),
    )


def _is_team_resource_query(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    context = message_input_context(event)
    target = _subscription_target(event)
    return target is not None and service.matches_target_query(
        event.get_plaintext(),
        actor=context.message.actor,
        target=target,
    )


def _is_team_resource_manage(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    context = message_input_context(event)
    command = service.parse_manage(event.get_plaintext())
    target = _subscription_target(event)
    return (
        command is not None
        and target is not None
        and service.allows_target(context.message.actor, target)
    )


def _is_team_resource_prompt_choice(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    context = message_input_context(event)
    target = TeamResourceSubscriptionTarget(context.message.conversation)
    return (
        parse_confirmation(event.get_plaintext()) is not None
        and _can_manage_event(service, event)
        and service.allows_target(context.message.actor, target)
        and service.has_pending_prompt(context.message.conversation)
    )


async def handle_team_resource_manage(
    matcher: Matcher,
    event: MessageEvent,
    service: TeamResourceService,
) -> None:
    context = message_input_context(event)
    target = _subscription_target(event)
    if target is None:
        await matcher.finish()

    command = service.parse_manage(event.get_plaintext())
    if command is None:
        await matcher.finish()

    if command.action == "list":
        await finish_event_reply(
            matcher,
            event,
            service.subscriptions_message(target),
        )
        return

    if isinstance(event, GroupMessageEvent) and not _can_manage_event(service, event):
        await finish_event_reply(
            matcher,
            event,
            "只有群主、管理员或超级管理员可以修改本群战队订阅。",
        )
        return

    team_id = command.team_id
    if team_id is None:
        await matcher.finish()

    if command.action == "remove":
        message = service.remove_target_subscription(
            target=target,
            team_id=team_id,
        )
    else:
        if command.has_manual_mention and target.is_group and not target.mention_actors:
            await finish_event_reply(
                matcher,
                event,
                "提醒对象请用 QQ 的 @ 选人功能添加；"
                "手动输入 @QQ号 不会保存为提醒对象。",
            )
            return
        message = await service.add_target_subscription(
            target=target,
            team_id=team_id,
            threshold=command.threshold,
            operator=context.message.actor,
        )
    await finish_event_reply(matcher, event, message)


async def handle_team_resource_prompt_choice(
    matcher: Matcher,
    event: GroupMessageEvent,
    service: TeamResourceService,
) -> None:
    context = message_input_context(event)
    choice = parse_confirmation(event.get_plaintext())
    if choice is None:
        await matcher.finish()
    message = service.answer_prompt(
        conversation=context.message.conversation,
        actor=context.message.actor,
        accepted=choice,
    )
    if message is None:
        await matcher.finish()
    await finish_event_reply(matcher, event, message)


async def handle_team_resource(
    matcher: Matcher,
    event: MessageEvent,
    service: TeamResourceService,
) -> None:
    target = _subscription_target(event)
    if target is None:
        await matcher.finish()

    messages = await service.query_target_messages(target)
    if not messages:
        await finish_event_reply(
            matcher,
            event,
            service.subscriptions_message(target),
        )
        return
    await finish_message_sequence(
        matcher,
        [Message(message) for message in messages],
        event=event,
    )


def install(
    registry: MatcherRegistry,
    service: TeamResourceService,
) -> None:
    def is_manage(event: MessageEvent) -> bool:
        return _is_team_resource_manage(event, service=service)

    def is_prompt_choice(event: MessageEvent) -> bool:
        return _is_team_resource_prompt_choice(event, service=service)

    def is_query(event: MessageEvent) -> bool:
        return _is_team_resource_query(event, service=service)

    priority = registry.priority("team_resource_subscription")
    manage_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "team_resource_manage",
            help_ids=(
                "team_resource.subscribe",
                "team_resource.unsubscribe",
                "team_resource.list",
            ),
        ),
        rule=Rule(is_manage) & member_targets_command(),
        priority=priority,
        block=True,
    )
    manage_matcher.append_handler(
        bind_async(handle_team_resource_manage, service=service)
    )

    prompt_matcher = registry.on_message(
        policy=CommandPolicy.exempt("second-level team subscription confirmation"),
        rule=Rule(is_prompt_choice) & explicit_command(),
        priority=priority,
        block=True,
    )
    prompt_matcher.append_handler(
        bind_async(handle_team_resource_prompt_choice, service=service)
    )

    query_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "team_resource_query",
            help_ids=("team_resource.query",),
        ),
        rule=Rule(is_query) & explicit_command(),
        priority=priority,
        block=True,
    )
    query_matcher.append_handler(bind_async(handle_team_resource, service=service))


def plugin_contribution(
    *,
    config: TeamResourceConfig,
    features: FeatureService,
    scheduler: Scheduler,
    service: TeamResourceService,
) -> PluginContribution:
    """Declare team resource commands, matchers, and scheduled scans."""

    return PluginContribution(
        id="team_resource",
        features=frozenset({Feature.TEAM_RESOURCE_SUBSCRIPTION}),
        help=HelpEntry(
            name="战队资源订阅",
            description="订阅战队，并在资源不足时定时提醒当前会话。",
            group="seer",
            order=50,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="team_resource_subscription",
                enabled=config.enabled,
            ),
        ),
        commands=command_descriptors(enabled=config.enabled),
        install=partial(install, service=service),
        hooks=PluginHooks(
            startup=(
                (
                    "team_resource_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )


def _can_manage_event(service: TeamResourceService, event: GroupMessageEvent) -> bool:
    return service.is_superuser(message_input_context(event).message.actor) or (
        is_group_owner_or_admin_event(event)
    )


def _mention_actors_from_event(event: GroupMessageEvent):
    return message_input_context(event).member_mentions


def _subscription_target(
    event: MessageEvent,
) -> TeamResourceSubscriptionTarget | None:
    context = message_input_context(event)
    if isinstance(event, GroupMessageEvent):
        return TeamResourceSubscriptionTarget(
            context.message.conversation,
            context.member_mentions,
        )
    if isinstance(event, PrivateMessageEvent):
        return TeamResourceSubscriptionTarget(context.message.actor)
    return None


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            config=context.settings.seer.team_resource,
            features=context.resources.features,
            scheduler=context.scheduler,
            service=context.resources.team_resource,
        ),
    )
