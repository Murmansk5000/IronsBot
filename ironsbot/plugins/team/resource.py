# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule

from ironsbot.core.commands import parse_confirmation
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply, finish_message_sequence
from ironsbot.runtime.rules import no_reply

if TYPE_CHECKING:
    from ironsbot.services.team.resource import TeamResourceService


def _is_team_resource_query(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    return isinstance(event, GroupMessageEvent) and service.matches_query(
        event.get_plaintext(),
        user_id=event.user_id,
        group_id=event.group_id,
    )


def _is_team_resource_manage(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    return (
        isinstance(event, GroupMessageEvent)
        and service.allows(event.user_id, event.group_id)
        and service.parse_manage(event.get_plaintext()) is not None
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
    event: GroupMessageEvent,
    service: TeamResourceService,
) -> None:
    command = service.parse_manage(event.get_plaintext())
    if command is None:
        await matcher.finish()

    if command.action == "list":
        await finish_event_reply(
            matcher,
            event,
            service.group_subscriptions_message(event.group_id),
        )
        return

    if not can_manage_group_event(service, event):
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
        message = service.remove_subscription(
            group_id=event.group_id,
            team_id=team_id,
        )
    else:
        at_user_ids = _at_user_ids_from_event(event)
        if command.has_manual_mention and not at_user_ids:
            await finish_event_reply(
                matcher,
                event,
                "提醒对象请用 QQ 的 @ 选人功能添加；"
                "手动输入 @QQ号 不会保存为提醒对象。",
            )
            return
        message = await service.add_subscription(
            group_id=event.group_id,
            team_id=team_id,
            threshold=command.threshold,
            at_user_ids=at_user_ids,
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
    event: GroupMessageEvent,
    service: TeamResourceService,
) -> None:
    messages = await service.query_group_messages(event.group_id)
    if not messages:
        await finish_event_reply(
            matcher,
            event,
            "本群还没有订阅战队。群主/管理员可发送“订阅战队123456”添加。",
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
        rule=Rule(is_manage) & no_reply(allow_at=True),
        priority=priority,
        block=True,
    )
    manage_matcher.append_handler(
        bind_async(handle_team_resource_manage, service=service)
    )

    prompt_matcher = registry.on_message(
        policy=CommandPolicy.exempt(
            "second-level team subscription confirmation"
        ),
        rule=Rule(is_prompt_choice) & no_reply(),
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
        rule=Rule(is_query) & no_reply(),
        priority=priority,
        block=True,
    )
    query_matcher.append_handler(bind_async(handle_team_resource, service=service))


def _at_user_ids_from_event(event: GroupMessageEvent) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            int(qq)
            for segment in event.message
            if segment.type == "at"
            and (qq := str(segment.data.get("qq", ""))).isdigit()
        )
    )
