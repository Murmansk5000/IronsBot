# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule

from ironsbot.core.commands import parse_confirmation
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command, member_targets_command
from ironsbot.services.team.resource import TeamResourceSubscriptionTarget

from .overview import TeamOverviewMenus

if TYPE_CHECKING:
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService


def _is_team_resource_query(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    target = _subscription_target(event)
    return target is not None and service.matches_target_query(
        event.get_plaintext(),
        user_id=event.user_id,
        target=target,
    )


def _is_team_resource_manage(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    command = service.parse_manage(event.get_plaintext())
    target = _subscription_target(event)
    return (
        command is not None
        and target is not None
        and service.allows_target(event.user_id, target)
    )


def _is_team_resource_prompt_choice(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    return (
        isinstance(event, GroupMessageEvent)
        and parse_confirmation(event.get_plaintext()) is not None
        and can_manage_group_event(service, event)
        and service.allows(event.user_id, event.group_id)
        and service.has_pending_prompt(event.group_id)
    )


async def handle_team_resource_manage(
    matcher: Matcher,
    event: MessageEvent,
    service: TeamResourceService,
    menus: TeamOverviewMenus,
) -> None:
    target = _subscription_target(event)
    if target is None:
        await matcher.finish()

    command = service.parse_manage(event.get_plaintext())
    if command is None:
        await matcher.finish()

    if command.action == "list":
        await handle_team_resource(matcher, event, service, menus)
        return

    if isinstance(event, GroupMessageEvent) and not can_manage_group_event(
        service,
        event,
    ):
        await finish_event_reply(
            matcher,
            event,
            "只有群主、管理员或超级管理员可以修改战队订阅。",
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
        if command.has_manual_mention and target.is_group and not target.at_user_ids:
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
            operator_id=event.user_id,
        )
    await finish_event_reply(matcher, event, message)


async def handle_team_resource_prompt_choice(
    matcher: Matcher,
    event: GroupMessageEvent,
    service: TeamResourceService,
) -> None:
    choice = parse_confirmation(event.get_plaintext())
    if choice is None:
        await matcher.finish()
    message = service.answer_prompt(
        group_id=event.group_id,
        user_id=event.user_id,
        accepted=choice,
    )
    if message is None:
        await matcher.finish()
    await finish_event_reply(matcher, event, message)


async def handle_team_resource(
    matcher: Matcher,
    event: MessageEvent,
    service: TeamResourceService,
    menus: TeamOverviewMenus,
) -> None:
    target = _subscription_target(event)
    if target is None:
        await matcher.finish()

    items = await service.query_overview(target)
    if not items:
        await finish_event_reply(
            matcher,
            event,
            service.subscriptions_message(target),
        )
        return
    await menus.open(matcher, event, items)


def install(
    registry: MatcherRegistry,
    service: TeamResourceService,
    team_query: SeerTeamQueryService,
    notice_timeout_seconds: float = 180,
) -> None:
    menus = TeamOverviewMenus(service, team_query, notice_timeout_seconds)
    menus.install(registry)

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
        bind_async(handle_team_resource_manage, service=service, menus=menus)
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
    query_matcher.append_handler(
        bind_async(handle_team_resource, service=service, menus=menus)
    )


def _at_user_ids_from_event(event: GroupMessageEvent) -> tuple[int, ...]:
    return message_input_context(event).member_user_ids


def _subscription_target(
    event: MessageEvent,
) -> TeamResourceSubscriptionTarget | None:
    if isinstance(event, GroupMessageEvent):
        return TeamResourceSubscriptionTarget(
            "group",
            event.group_id,
            _at_user_ids_from_event(event),
        )
    if isinstance(event, PrivateMessageEvent):
        return TeamResourceSubscriptionTarget("private", event.user_id)
    return None
