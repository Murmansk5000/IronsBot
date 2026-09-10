# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.matchers import CommandPolicy, bind, bind_async
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import member_target_command, startswith_or_endswith
from ironsbot.services.seer.team import TeamQueryActor

from ..group import SeerMatcherGroup, seer_feature_rule
from .player_target import (
    PlayerTargetResolution,
    protected_shortcut_target_error,
    resolve_event_player_target,
)
from .player_target_selection import enter_player_target_selection

TEAM_IDS_KEY = "_team_ids"
PLAYER_TARGET_KEY = "_team_player_target"


def _capture_team_ids(
    group: SeerMatcherGroup,
    event: MessageEvent,
    state: T_State,
) -> bool:
    text = message_input_context(event).text.strip()
    prefix = "查询战队信息" if text.startswith("查询战队信息") else "战队"
    if not text.startswith(prefix):
        return False
    reference = text.removeprefix(prefix).strip()
    if not message_input_context(event).has_member_mentions and re.fullmatch(
        r"\d+(?:\s+\d+)*",
        reference,
    ):
        state[TEAM_IDS_KEY] = group.resources.team_query.parse_team_ids(reference)
        return True
    if reference.startswith("米米号"):
        reference = reference.removeprefix("米米号").strip()
    target = resolve_event_player_target(
        group.player_accounts,
        event,
        reference,
        binding_for_user=group.resources.player.default_player_id,
        allow_private=group.features.is_superuser(event.user_id),
        allow_default=False,
        allow_partial_reference=True,
    )
    state[PLAYER_TARGET_KEY] = target
    return target.recognized


async def _handle_team_query(
    group: SeerMatcherGroup,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    group_id = int(event.group_id) if isinstance(event, GroupMessageEvent) else None
    actor = TeamQueryActor(
        user_id=int(event.user_id),
        group_id=group_id,
        can_manage=can_manage_group_event(group.features, event),
    )
    target = state.get(PLAYER_TARGET_KEY)
    if isinstance(target, PlayerTargetResolution):
        if target.error:
            await finish_event_reply(matcher, event, target.error)
            return

        async def select(
            player_id: int,
            selected: Matcher,
            source: MessageEvent,
        ) -> None:
            await _query_player_team(
                group,
                PlayerTargetResolution(
                    player_id,
                    offer_binding=False,
                    is_shortcut_target=target.is_shortcut_target,
                ),
                selected,
                source,
            )

        if target.choices:
            await enter_player_target_selection(matcher, event, state, target, select)
        elif target.player_id is not None:
            await select(target.player_id, matcher, event)
        return
    reply = await group.resources.team_query.query(state[TEAM_IDS_KEY], actor)
    await finish_event_reply(matcher, event, reply)


async def _query_player_team(
    group: SeerMatcherGroup,
    target: PlayerTargetResolution,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    player_id = target.player_id
    if player_id is None:
        return
    error = protected_shortcut_target_error(
        group.resources.player,
        event.user_id,
        target,
    )
    if error:
        await finish_event_reply(matcher, event, error)
        return
    reply = await group.resources.team_query.query_player_team(
        player_id,
        TeamQueryActor(
            event.user_id,
            event.group_id if isinstance(event, GroupMessageEvent) else None,
            can_manage_group_event(group.features, event),
        ),
    )
    await finish_event_reply(matcher, event, reply)


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team", help_ids=("seer.team.query",)),
        rule=seer_feature_rule(group.features, "seer_team")
        & startswith_or_endswith(
            prefixes=("战队", "查询战队信息"),
            suffixes=(),
        )
        & Rule(bind(_capture_team_ids, group))
        & member_target_command(),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(bind_async(_handle_team_query, group))
