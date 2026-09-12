# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.integrations.onebot.matchers import CommandPolicy, bind, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.params import parse_string_arg
from ironsbot.integrations.onebot.permissions import can_manage_group_event
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import affix_command, explicit_command
from ironsbot.services.seer.query_commands import team_query_input
from ironsbot.services.seer.team import TeamQueryActor

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.team import SeerTeamQueryService

TEAM_IDS_KEY = "_team_ids"


def _capture_team_ids(
    service: SeerTeamQueryService,
    state: T_State,
) -> bool:
    team_ids = service.parse_team_ids(parse_string_arg(state))
    if not team_ids:
        return False
    state[TEAM_IDS_KEY] = team_ids
    return True


async def _handle_team_query(
    service: SeerTeamQueryService,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    context = message_input_context(event)
    reply = await service.query(
        state[TEAM_IDS_KEY],
        TeamQueryActor(
            actor=context.message.actor,
            conversation=(
                context.message.conversation
                if isinstance(event, GroupMessageEvent)
                else None
            ),
            can_manage=can_manage_group_event(features, event),
        ),
    )
    await finish_event_reply(matcher, event, reply)


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.team_query
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team", help_ids=("seer.team.query",)),
        rule=seer_feature_rule(group.features, "seer_team")
        & affix_command(team_query_input)
        & Rule(bind(_capture_team_ids, service))
        & explicit_command(),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(bind_async(_handle_team_query, service, group.features))
